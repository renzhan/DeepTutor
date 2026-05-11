"""
Guided Solve Capability
=======================

K12 数学引导式辅导：苏格拉底式提问引导学生自主解题。

Orchestrates a four-stage pipeline:
1. analyzing  — Parse problem, identify knowledge points
2. guiding    — Socratic-method step-by-step guidance
3. validating — Verify student answers
4. summarizing — Generate solve summary and update mastery

Supports multi-turn conversation with session state persistence
in UnifiedContext.metadata.

Requirements: 1.1, 1.3, 1.4, 1.5, 8.1, 8.2, 8.3, 8.4, 8.5, 10.1, 10.2, 10.3, 10.4, 10.5
"""

from __future__ import annotations

import logging
from pathlib import Path

from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Abandon detection keywords
# ─────────────────────────────────────────────────────────────────────────────

_ABANDON_KEYWORDS = ["放弃", "不做了", "跳过", "abandon", "skip", "quit"]


class GuidedSolveCapability(BaseCapability):
    """K12 guided math tutoring capability using Socratic method."""

    manifest = CapabilityManifest(
        name="guided_solve",
        description="K12 数学引导式辅导：苏格拉底式提问引导学生自主解题。",
        stages=["analyzing", "guiding", "validating", "summarizing"],
        tools_used=["rag", "code_execution"],
        cli_aliases=["guided_solve", "tutor"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        """
        Main orchestration:
        1. Check if resuming from existing session state
        2. If new problem: run analyzing stage
        3. Run guiding/validating loop
        4. When complete: run summarizing stage
        5. Emit DONE event

        Handle abandon: if user message contains abandon keywords,
        save progress and exit gracefully.

        Error handling (Requirements 2.3, 4.4, 10.1, 10.5):
        - KnowledgeGraph loading failure: use empty graph
        - ProblemAnalyzer failure: emit error and DONE
        - AnswerValidator failure: already has timeout fallback
        - SolveSummarizer failure: still emit DONE
        - StudentProfile loading failure: use temporary profile
        """
        from deeptutor.k12.agents.answer_validator import AnswerValidator
        from deeptutor.k12.agents.problem_analyzer import AnalysisResult, ProblemAnalyzer
        from deeptutor.k12.agents.socratic_guide import (
            GuidanceLevel,
            GuidanceState,
            GuidanceStep,
            SocraticGuide,
        )
        from deeptutor.k12.agents.solve_summarizer import SolveSummarizer
        from deeptutor.k12.knowledge_graph import KnowledgeGraph
        from deeptutor.k12.models import CompletionType, SolvingSessionState
        from deeptutor.k12.student_profile import StudentProfileService

        # ── Load or restore session state ────────────────────────────────
        session_data = context.metadata.get("solving_session_state")

        if session_data:
            session_state = SolvingSessionState.model_validate(session_data)
        else:
            session_state = None

        # ── Check for abandon ────────────────────────────────────────────
        user_msg_lower = context.user_message.lower()
        if any(kw in user_msg_lower for kw in _ABANDON_KEYWORDS):
            await self._handle_abandon(context, stream, session_state)
            return

        # ── Initialize services (with error handling) ────────────────────
        data_dir = Path("deeptutor/k12/data")
        try:
            kg = KnowledgeGraph(data_dir=data_dir)
        except Exception as exc:
            logger.warning("KnowledgeGraph loading failed: %s, using empty graph", exc)
            kg = KnowledgeGraph()  # Empty graph fallback

        try:
            profile_service = StudentProfileService()
        except Exception as exc:
            logger.warning("StudentProfileService init failed: %s", exc)
            profile_service = StudentProfileService()

        if session_state is None:
            # ── New problem: run analyzing stage ─────────────────────────
            try:
                async with stream.stage("analyzing", source=self.name):
                    analyzer = ProblemAnalyzer(kg)
                    analysis = await analyzer.analyze(
                        problem_text=context.user_message,
                        attachments=context.attachments,
                        kb_name=(
                            context.knowledge_bases[0]
                            if context.knowledge_bases
                            else None
                        ),
                        stream=stream,
                    )

                    # Determine guidance level from mastery scores
                    guide = SocraticGuide(kg, profile_service)
                    mastery_scores: list[float] = []
                    level = guide.determine_guidance_level(mastery_scores)

                    # Generate guidance steps
                    steps = await guide.generate_steps(
                        problem_text=context.user_message,
                        knowledge_point_ids=analysis.knowledge_points,
                        guidance_level=level,
                        stream=stream,
                    )

                    # Initialize session state
                    session_state = SolvingSessionState(
                        problem_text=context.user_message,
                        analysis_result={
                            "knowledge_points": analysis.knowledge_points,
                            "difficulty": analysis.difficulty_estimate,
                        },
                        current_step=0,
                        total_steps=len(steps),
                        guidance_level=level.value,
                        steps=[
                            {
                                "question": s.question,
                                "hint": s.hint,
                                "expected_direction": s.expected_direction,
                                "knowledge_point_id": s.knowledge_point_id,
                            }
                            for s in steps
                        ],
                    )

                    # Emit first guidance question
                    if steps:
                        await stream.content(
                            steps[0].question, source=self.name, stage="analyzing"
                        )

                    # Report progress
                    await stream.progress(
                        message="分析完成，开始引导",
                        current=0,
                        total=len(steps),
                        source=self.name,
                        stage="analyzing",
                    )

                    # Record this problem attempt to database
                    wx_token = context.metadata.get("wx_token", "")
                    logger.warning(
                        "[DEBUG] Analyzing complete: wx_token=%r, kp_count=%d",
                        wx_token, len(analysis.knowledge_points),
                    )
                    for kp_id in analysis.knowledge_points[:3]:  # Record top 3 knowledge points
                        await self._record_step_attempt(
                            student_id=wx_token or "default_student",
                            knowledge_point_id=kp_id,
                            knowledge_point_name=kp_id,
                            is_correct=True,  # Attempting a problem counts as engagement
                            kg=kg,
                        )
            except Exception as exc:
                logger.error("Problem analysis failed: %s", exc)
                await stream.error(
                    f"题目分析失败，请稍后重试。",
                    source=self.name,
                    stage="analyzing",
                )
                await stream.emit(
                    StreamEvent(type=StreamEventType.DONE, source=self.name)
                )
                return
        else:
            # ── Resume: run guiding/validating for current step ──────────
            guide = SocraticGuide(kg, profile_service)
            validator = AnswerValidator()

            current_step_idx = session_state.current_step

            if current_step_idx < session_state.total_steps:
                step_data = session_state.steps[current_step_idx]
                current_step = GuidanceStep(
                    step_index=current_step_idx,
                    question=step_data["question"],
                    hint=step_data["hint"],
                    expected_direction=step_data["expected_direction"],
                    knowledge_point_id=step_data["knowledge_point_id"],
                )

                # Validate student answer (already has timeout fallback)
                try:
                    async with stream.stage("validating", source=self.name):
                        result = await validator.validate(
                            student_answer=context.user_message,
                            expected_direction=current_step.expected_direction,
                            step=current_step,
                            stream=stream,
                        )
                except Exception as exc:
                    logger.warning(
                        "Validation failed for step %d: %s, treating as incorrect",
                        current_step_idx,
                        exc,
                    )
                    # Fallback: treat as incorrect answer so student can retry
                    from deeptutor.k12.agents.answer_validator import ValidationResult

                    result = ValidationResult(
                        is_correct=False,
                        method="llm_fallback",
                        feedback="验证服务暂时不可用，请再试一次。",
                        error_direction="",
                        code_output="",
                    )

                # Build GuidanceState from session_state
                all_steps = [
                    GuidanceStep(
                        step_index=i,
                        question=s["question"],
                        hint=s["hint"],
                        expected_direction=s["expected_direction"],
                        knowledge_point_id=s["knowledge_point_id"],
                    )
                    for i, s in enumerate(session_state.steps)
                ]

                error_count_int: dict[int, int] = {}
                for k, v in session_state.error_count.items():
                    # Keys are "step_0", "step_1", etc.
                    try:
                        idx = int(k.replace("step_", ""))
                        error_count_int[idx] = v
                    except (ValueError, AttributeError):
                        pass

                guidance_state = GuidanceState(
                    current_step=session_state.current_step,
                    total_steps=session_state.total_steps,
                    completed_steps=list(session_state.completed_steps),
                    error_count=error_count_int,
                    guidance_level=GuidanceLevel(session_state.guidance_level),
                    steps=all_steps,
                    independent_steps=list(session_state.independent_steps),
                )

                # Provide guidance based on validation result
                async with stream.stage("guiding", source=self.name):
                    updated_state = await guide.provide_guidance(
                        state=guidance_state,
                        student_answer=context.user_message,
                        is_correct=result.is_correct,
                        stream=stream,
                    )

                # Update session state from guidance result
                session_state.current_step = updated_state.current_step
                session_state.completed_steps = updated_state.completed_steps
                session_state.error_count = {
                    f"step_{k}": v for k, v in updated_state.error_count.items()
                }
                session_state.guidance_level = updated_state.guidance_level.value
                session_state.independent_steps = updated_state.independent_steps

                # Record this step's attempt to database immediately
                wx_token = context.metadata.get("wx_token", "")
                logger.warning(
                    "[DEBUG] Recording attempt: wx_token=%r, metadata_keys=%s, kp=%s, correct=%s",
                    wx_token, list(context.metadata.keys()), current_step.knowledge_point_id, result.is_correct,
                )
                await self._record_step_attempt(
                    student_id=wx_token or "default_student",
                    knowledge_point_id=current_step.knowledge_point_id,
                    knowledge_point_name=current_step.knowledge_point_id,
                    is_correct=result.is_correct,
                    kg=kg,
                )

                # Report progress
                await stream.progress(
                    message=f"步骤 {updated_state.current_step}/{updated_state.total_steps}",
                    current=updated_state.current_step,
                    total=updated_state.total_steps,
                    source=self.name,
                    stage="guiding",
                )

                # Check if all steps complete → summarize
                if updated_state.current_step >= updated_state.total_steps:
                    session_state.is_complete = True

                    try:
                        async with stream.stage("summarizing", source=self.name):
                            summarizer = SolveSummarizer(profile_service)

                            # Build profile for summarization
                            kp_ids = session_state.analysis_result.get(
                                "knowledge_points", []
                            )
                            profile_data = profile_service.create_profile(
                                context.session_id or "anonymous",
                                "7",
                                "1",
                                "人教版",
                                kg,
                            )

                            analysis_result = AnalysisResult(
                                problem_text=session_state.problem_text,
                                knowledge_points=kp_ids,
                                difficulty_estimate=session_state.analysis_result.get(
                                    "difficulty", 1
                                ),
                                solution_steps=[],
                            )

                            await summarizer.summarize(
                                updated_state, analysis_result, profile_data, stream
                            )

                            # Persist mastery updates to student data file
                            wx_token = context.metadata.get("wx_token", "")
                            await self._persist_mastery_updates(
                                updated_state, session_state, kg, wx_token=wx_token
                            )
                    except Exception as exc:
                        logger.warning("Summarization failed: %s", exc)
                        await stream.content(
                            "解题完成！总结生成暂时不可用。",
                            source=self.name,
                            stage="summarizing",
                        )

        # ── Save session state to metadata for next turn ─────────────────
        context.metadata["solving_session_state"] = session_state.model_dump()

        # ── Emit DONE event ──────────────────────────────────────────────
        await stream.emit(StreamEvent(type=StreamEventType.DONE, source=self.name))

    async def _record_step_attempt(
        self,
        student_id: str,
        knowledge_point_id: str,
        knowledge_point_name: str,
        is_correct: bool,
        kg: object,
    ) -> None:
        """Record a single step attempt to PostgreSQL immediately."""
        try:
            from deeptutor.api.routers.student import (
                _ensure_tables,
                _ensure_student,
                get_conn,
            )

            import time as _time

            _ensure_tables()
            now = _time.time()

            # Get display name from knowledge graph
            point = kg.get_point(knowledge_point_id) if kg else None
            kp_name = point.name if point else knowledge_point_name

            with get_conn() as conn:
                with conn.cursor() as cur:
                    _ensure_student(cur, student_id)

                    # Record attempt
                    cur.execute(
                        """INSERT INTO k12_attempts
                           (student_id, knowledge_point, correct, timestamp, duration_seconds)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (student_id, knowledge_point_id, is_correct, now, 60),
                    )

                    # Update mastery score
                    cur.execute(
                        "SELECT score FROM k12_mastery WHERE student_id = %s AND knowledge_point_id = %s",
                        (student_id, knowledge_point_id),
                    )
                    row = cur.fetchone()
                    old_score = row[0] if row else 0.0

                    if is_correct:
                        new_score = min(1.0, old_score + 0.12)
                    else:
                        new_score = max(0.0, old_score - 0.05)

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
                        (student_id, knowledge_point_id, kp_name, new_score, now,
                         kp_name, new_score, now),
                    )

            logger.info(
                "Recorded attempt: student=%s kp=%s correct=%s score=%.2f",
                student_id[:8], knowledge_point_id, is_correct, new_score,
            )

        except Exception as exc:
            logger.warning("Failed to record step attempt: %s", exc)

    async def _persist_mastery_updates(
        self,
        guidance_state: object,
        session_state: object,
        kg: object,
        wx_token: str = "",
    ) -> None:
        """Persist mastery updates to PostgreSQL after completing a problem."""
        try:
            from deeptutor.api.routers.student import (
                _ensure_tables,
                _ensure_student,
                get_conn,
            )

            import time as _time

            _ensure_tables()
            # Use wx_token (openid) as student_id, fallback to default
            student_id = wx_token if wx_token else "default_student"
            now = _time.time()

            with get_conn() as conn:
                with conn.cursor() as cur:
                    _ensure_student(cur, student_id)

                    for step in guidance_state.steps:
                        kp_id = step.knowledge_point_id
                        point = kg.get_point(kp_id) if kg else None
                        kp_name = point.name if point else kp_id

                        is_independent = step.step_index in guidance_state.independent_steps
                        delta = 0.15 if is_independent else 0.08

                        # Get current score
                        cur.execute(
                            "SELECT score FROM k12_mastery WHERE student_id = %s AND knowledge_point_id = %s",
                            (student_id, kp_id),
                        )
                        row = cur.fetchone()
                        old_score = row[0] if row else 0.0
                        new_score = min(1.0, old_score + delta)

                        # Upsert mastery
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
                            (student_id, kp_id, kp_name, new_score, now, kp_name, new_score, now),
                        )

                        # Record attempt
                        cur.execute(
                            """INSERT INTO k12_attempts
                               (student_id, knowledge_point, correct, timestamp, duration_seconds)
                               VALUES (%s, %s, %s, %s, %s)""",
                            (student_id, kp_id, is_independent, now, 60),
                        )

            logger.info("Persisted mastery updates to PostgreSQL for %d knowledge points", len(guidance_state.steps))

        except Exception as exc:
            logger.warning("Failed to persist mastery updates: %s", exc)

    async def _handle_abandon(
        self,
        context: UnifiedContext,
        stream: StreamBus,
        session_state: object | None,
    ) -> None:
        """Handle problem abandonment: save progress and emit DONE."""
        from deeptutor.k12.models import SolvingSessionState

        if session_state is not None and isinstance(session_state, SolvingSessionState):
            session_state.is_abandoned = True
            context.metadata["solving_session_state"] = session_state.model_dump()

        await stream.content(
            "好的，我们先跳过这道题。下次可以继续练习相关知识点。",
            source=self.name,
            stage="summarizing",
        )
        await stream.emit(StreamEvent(type=StreamEventType.DONE, source=self.name))
