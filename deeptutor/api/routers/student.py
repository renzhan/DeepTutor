"""
Student Profile API Router (PostgreSQL / Supabase)
===================================================

REST endpoints for K12 student profile management, backed by PostgreSQL.
Tables are auto-created on first request.

- POST /api/v1/student/wx-login      — WeChat login (code → openid)
- GET  /api/v1/student/mastery       — knowledge point mastery data
- GET  /api/v1/student/stats/week    — last 7 days learning statistics
- POST /api/v1/student/profile       — create/update student profile
- GET  /api/v1/student/profile       — get student profile
- POST /api/v1/student/attempt       — record a problem attempt
- POST /api/v1/student/mastery/update — batch update mastery scores
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Generator

import httpx
import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── WeChat config ───────────────────────────────────────────────────────────

WX_APPID = os.getenv("WX_APPID", "wx72d80599806ba1c0")
WX_APP_SECRET = os.getenv("WX_APP_SECRET", "dc8dde4e0d615ed766d0f631856830e6")

# ─── Database connection ─────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "K12_DATABASE_URL",
    "postgresql://postgres:v7%40Hypj5v6bM7F4x@db.bzlkyanfzrmhiemhssas.supabase.co:5432/postgres",
)

_tables_created = False


@contextmanager
def get_conn() -> Generator[Any, None, None]:
    """Get a PostgreSQL connection (auto-commit mode)."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def _ensure_tables() -> None:
    """Create tables if they don't exist (idempotent)."""
    global _tables_created
    if _tables_created:
        return

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS k12_students (
                    student_id TEXT PRIMARY KEY,
                    grade TEXT DEFAULT '',
                    textbook TEXT DEFAULT '',
                    created_at DOUBLE PRECISION DEFAULT 0,
                    updated_at DOUBLE PRECISION DEFAULT 0
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS k12_mastery (
                    id SERIAL PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    knowledge_point_id TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    score DOUBLE PRECISION DEFAULT 0.0,
                    last_updated DOUBLE PRECISION DEFAULT 0,
                    attempt_count INTEGER DEFAULT 0,
                    UNIQUE(student_id, knowledge_point_id)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS k12_attempts (
                    id SERIAL PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    knowledge_point TEXT NOT NULL,
                    correct BOOLEAN DEFAULT FALSE,
                    timestamp DOUBLE PRECISION DEFAULT 0,
                    duration_seconds DOUBLE PRECISION DEFAULT 0
                );
            """)
            # Index for fast week-stats query
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_k12_attempts_student_ts
                ON k12_attempts(student_id, timestamp);
            """)

    _tables_created = True
    logger.info("K12 database tables ensured.")


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _get_student_id(request: Request) -> str:
    """
    Extract student ID from request.
    
    Reads the Authorization header token:
    - Dev mode tokens like "dev_token_xxx" → use as-is
    - Production: would be wx openid extracted from JWT
    
    Falls back to "default_student" if no token present.
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            # Use the token value as student_id (dev_token_xxx or openid)
            return token

    # Also check query param (for WebSocket-initiated requests)
    token = request.query_params.get("token", "")
    if token:
        return token

    return "default_student"


def _ensure_student(cur: Any, student_id: str) -> None:
    """Ensure student record exists."""
    cur.execute(
        """INSERT INTO k12_students (student_id, created_at, updated_at)
           VALUES (%s, %s, %s)
           ON CONFLICT (student_id) DO NOTHING""",
        (student_id, time.time(), time.time()),
    )


# ─── Models ──────────────────────────────────────────────────────────────────


class ProfileRequest(BaseModel):
    grade: str = ""
    textbook: str = ""


class AttemptRecord(BaseModel):
    knowledge_point: str
    correct: bool
    timestamp: float = 0
    duration_seconds: float = 0


# ─── Endpoints ───────────────────────────────────────────────────────────────


class WxLoginRequest(BaseModel):
    code: str


@router.post("/wx-login")
async def wx_login(body: WxLoginRequest) -> dict:
    """
    WeChat Mini Program login.
    
    Receives the wx.login() code, calls WeChat code2session API to get openid,
    then returns a token (the openid itself) for subsequent requests.
    """
    _ensure_tables()

    code = body.code
    if not code:
        return {"error": "code is required"}, 400

    # Call WeChat code2session API
    wx_url = (
        f"https://api.weixin.qq.com/sns/jscode2session"
        f"?appid={WX_APPID}"
        f"&secret={WX_APP_SECRET}"
        f"&js_code={code}"
        f"&grant_type=authorization_code"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(wx_url)
            data = resp.json()
    except Exception as exc:
        logger.error("WeChat code2session failed: %s", exc)
        return {"error": "微信登录服务暂时不可用", "token": f"fallback_{int(time.time())}"}

    openid = data.get("openid", "")
    session_key = data.get("session_key", "")
    errcode = data.get("errcode", 0)

    if errcode != 0 or not openid:
        logger.warning("WeChat code2session error: %s", data)
        # Fallback for dev: use code as identifier
        openid = f"wx_code_{code[:16]}"

    # Ensure student record exists in DB
    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_student(cur, openid)

    logger.info("WeChat login success: openid=%s", openid[:8] + "...")

    return {
        "token": openid,
        "userInfo": {
            "studentId": openid,
            "name": f"微信用户",
        },
    }


@router.post("/profile")
async def create_or_update_profile(body: ProfileRequest, request: Request) -> dict:
    """Create or update student profile (grade, textbook)."""
    _ensure_tables()
    student_id = _get_student_id(request)

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_student(cur, student_id)
            cur.execute(
                """UPDATE k12_students
                   SET grade = %s, textbook = %s, updated_at = %s
                   WHERE student_id = %s""",
                (body.grade, body.textbook, time.time(), student_id),
            )

    return {"ok": True, "message": "Profile updated"}


@router.get("/profile")
async def get_profile(request: Request) -> dict:
    """Get student profile."""
    _ensure_tables()
    student_id = _get_student_id(request)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _ensure_student(cur, student_id)
            cur.execute(
                "SELECT student_id, grade, textbook FROM k12_students WHERE student_id = %s",
                (student_id,),
            )
            row = cur.fetchone()

    if row:
        return dict(row)
    return {"student_id": student_id, "grade": "", "textbook": ""}


@router.get("/mastery")
async def get_mastery(request: Request) -> dict:
    """Get knowledge point mastery data for the student."""
    _ensure_tables()
    student_id = _get_student_id(request)

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT knowledge_point_id, name, score, attempt_count
                   FROM k12_mastery
                   WHERE student_id = %s
                   ORDER BY score DESC""",
                (student_id,),
            )
            rows = cur.fetchall()

    mastery_list = []
    for row in rows:
        score = row["score"]
        if score < 0.4:
            level = "weak"
        elif score < 0.7:
            level = "developing"
        elif score < 0.85:
            level = "proficient"
        else:
            level = "mastered"

        mastery_list.append({
            "name": row["name"] or row["knowledge_point_id"],
            "id": row["knowledge_point_id"],
            "score": score,
            "level": level,
        })

    return {"data": mastery_list}


@router.get("/stats/week")
async def get_week_stats(request: Request) -> dict:
    """Get last 7 days learning statistics."""
    _ensure_tables()
    student_id = _get_student_id(request)

    seven_days_ago = time.time() - 7 * 24 * 60 * 60

    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT
                     COUNT(*) as total,
                     COUNT(*) FILTER (WHERE correct = TRUE) as correct_count,
                     COALESCE(SUM(duration_seconds), 0) as total_seconds
                   FROM k12_attempts
                   WHERE student_id = %s AND timestamp >= %s""",
                (student_id, seven_days_ago),
            )
            row = cur.fetchone()

    total = row["total"] if row else 0
    correct_count = row["correct_count"] if row else 0
    total_seconds = row["total_seconds"] if row else 0

    correct_rate = round(correct_count / total * 100) if total > 0 else 0
    study_minutes = round(total_seconds / 60)

    return {
        "totalQuestions": total,
        "correctRate": correct_rate,
        "studyMinutes": study_minutes,
    }


@router.post("/attempt")
async def record_attempt(body: AttemptRecord, request: Request) -> dict:
    """Record a problem attempt and update mastery score."""
    _ensure_tables()
    student_id = _get_student_id(request)
    ts = body.timestamp or time.time()

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_student(cur, student_id)

            # Insert attempt record
            cur.execute(
                """INSERT INTO k12_attempts
                   (student_id, knowledge_point, correct, timestamp, duration_seconds)
                   VALUES (%s, %s, %s, %s, %s)""",
                (student_id, body.knowledge_point, body.correct, ts, body.duration_seconds),
            )

            # Upsert mastery score
            kp_id = body.knowledge_point

            # Get current score
            cur.execute(
                """SELECT score FROM k12_mastery
                   WHERE student_id = %s AND knowledge_point_id = %s""",
                (student_id, kp_id),
            )
            row = cur.fetchone()
            old_score = row[0] if row else 0.0

            # Apply mastery update
            if body.correct:
                new_score = min(1.0, old_score + 0.12)
            else:
                new_score = max(0.0, old_score - 0.05)

            cur.execute(
                """INSERT INTO k12_mastery
                   (student_id, knowledge_point_id, name, score, last_updated, attempt_count)
                   VALUES (%s, %s, %s, %s, %s, 1)
                   ON CONFLICT (student_id, knowledge_point_id)
                   DO UPDATE SET
                     score = %s,
                     last_updated = %s,
                     attempt_count = k12_mastery.attempt_count + 1""",
                (student_id, kp_id, kp_id, new_score, ts, new_score, ts),
            )

    return {"ok": True, "new_score": new_score}


@router.post("/mastery/update")
async def update_mastery_direct(request: Request) -> dict:
    """
    Batch update mastery scores (called after completing a guided solve session).
    Body: {"updates": [{"id": "kp_id", "name": "名称", "completion_type": "independent|guided|failed"}]}
    """
    _ensure_tables()
    student_id = _get_student_id(request)
    body = await request.json()
    updates = body.get("updates", [])
    now = time.time()

    deltas = {"independent": 0.15, "guided": 0.08, "failed": -0.05}

    with get_conn() as conn:
        with conn.cursor() as cur:
            _ensure_student(cur, student_id)

            for update in updates:
                kp_id = update.get("id", "")
                if not kp_id:
                    continue

                name = update.get("name", kp_id)
                completion_type = update.get("completion_type", "guided")
                delta = deltas.get(completion_type, 0.08)

                # Get current score
                cur.execute(
                    "SELECT score FROM k12_mastery WHERE student_id = %s AND knowledge_point_id = %s",
                    (student_id, kp_id),
                )
                row = cur.fetchone()
                old_score = row[0] if row else 0.0
                new_score = max(0.0, min(1.0, old_score + delta))

                # Upsert
                cur.execute(
                    """INSERT INTO k12_mastery
                       (student_id, knowledge_point_id, name, score, last_updated, attempt_count)
                       VALUES (%s, %s, %s, %s, %s, 1)
                       ON CONFLICT (student_id, knowledge_point_id)
                       DO UPDATE SET
                         name = %s,
                         score = %s,
                         last_updated = %s,
                         attempt_count = k12_mastery.attempt_count + 1""",
                    (student_id, kp_id, name, new_score, now, name, new_score, now),
                )

    return {"ok": True, "updated": len(updates)}


@router.get("/practice")
async def get_practice_set(request: Request, count: int = 5) -> dict:
    """
    Generate a practice problem set for the student.
    Uses LLM to generate diverse problems based on student's mastery profile.
    """
    _ensure_tables()
    student_id = _get_student_id(request)

    # Get student's mastery data to determine weak/review/challenge distribution
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT knowledge_point_id, score FROM k12_mastery WHERE student_id = %s",
                (student_id,),
            )
            mastery_rows = cur.fetchall()

    # Build mastery profile for PracticeGenerator
    from pathlib import Path

    from deeptutor.k12.knowledge_graph import KnowledgeGraph
    from deeptutor.k12.models import MasteryRecord, StudentProfileData
    from deeptutor.k12.practice_generator import PracticeGenerator

    kg = KnowledgeGraph(data_dir=Path("deeptutor/k12/data"))

    # Build StudentProfileData from DB records
    mastery_dict = {}
    for row in mastery_rows:
        kp_id = row["knowledge_point_id"]
        mastery_dict[kp_id] = MasteryRecord(
            knowledge_point_id=kp_id,
            score=row["score"],
        )

    # If no mastery data, add all knowledge points with score 0
    if not mastery_dict:
        for kp_id in kg.node_ids:
            mastery_dict[kp_id] = MasteryRecord(
                knowledge_point_id=kp_id,
                score=0.0,
            )

    profile = StudentProfileData(
        student_id=student_id,
        grade="7",
        semester="1",
        textbook_version="人教版",
        mastery=mastery_dict,
    )

    # Generate practice set
    generator = PracticeGenerator(kg)
    problems = await generator.generate_practice_set(profile, count=count)

    # Format for frontend
    questions = []
    for i, p in enumerate(problems):
        point = kg.get_point(p.knowledge_points[0]) if p.knowledge_points else None
        questions.append({
            "id": str(i + 1),
            "content": p.problem_text,
            "answer": p.reference_answer,
            "difficulty": ["easy", "easy", "medium", "hard", "hard"][min(p.difficulty - 1, 4)],
            "knowledgePoint": point.name if point else (p.knowledge_points[0] if p.knowledge_points else ""),
        })

    return {"questions": questions}


@router.post("/practice/check-answer")
async def check_practice_answer(request: Request) -> dict:
    """
    Use LLM to check if a student's answer is correct.
    Handles format differences (e.g., "2" vs "x=2" vs "x = 2").
    
    Body: {"question": "题目", "reference_answer": "参考答案", "student_answer": "学生答案"}
    """
    body = await request.json()
    question = body.get("question", "")
    reference_answer = body.get("reference_answer", "")
    student_answer = body.get("student_answer", "")

    if not student_answer.strip():
        return {"correct": False, "feedback": "请输入答案"}

    # Quick exact match (handles trivial cases)
    if student_answer.strip() == reference_answer.strip():
        return {"correct": True, "feedback": "回答正确！"}

    # Use LLM to judge
    try:
        from deeptutor.services.llm import complete

        prompt = (
            f"判断学生的数学答案是否正确。\n\n"
            f"题目：{question}\n"
            f"参考答案：{reference_answer}\n"
            f"学生答案：{student_answer}\n\n"
            f"注意：只要数学含义相同就算正确，不要求格式完全一致。"
            f"例如 'x=2' 和 '2' 和 'x = 2' 都是正确的。\n\n"
            f"只输出JSON：{{\"correct\": true/false, \"feedback\": \"简短反馈\"}}"
        )

        response = await complete(
            prompt,
            system_prompt="你是数学老师，判断答案正确性。只输出JSON，不要其他内容。",
            max_tokens=200,
        )

        import json
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        data = json.loads(text)
        return {
            "correct": data.get("correct", False),
            "feedback": data.get("feedback", ""),
        }

    except Exception as exc:
        logger.warning("LLM answer check failed: %s, falling back to string match", exc)
        # Fallback: loose string matching
        s = student_answer.strip().lower().replace(" ", "").replace("=", "")
        r = reference_answer.strip().lower().replace(" ", "").replace("=", "")
        is_correct = s in r or r in s
        return {
            "correct": is_correct,
            "feedback": "回答正确！" if is_correct else "答案不太对，再想想。",
        }
