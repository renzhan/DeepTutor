"""
K12 Data Models
===============

Core data structures for student profiles, knowledge graphs,
and teaching strategies.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class Semester(str, Enum):
    UP = "up"  # 上学期
    DOWN = "down"  # 下学期


class Textbook(str, Enum):
    RENJIAOBAN = "renjiaoban"  # 人教版
    BEISHIDA = "beishida"  # 北师大版
    SUJIAO = "sujiao"  # 苏教版
    HUJIAO = "hujiao"  # 沪教版


class MasteryLevel(str, Enum):
    """Knowledge point mastery classification."""

    NOT_STARTED = "not_started"  # 未学习
    BEGINNER = "beginner"  # 了解 (< 0.3)
    DEVELOPING = "developing"  # 理解 (0.3 - 0.6)
    PROFICIENT = "proficient"  # 掌握 (0.6 - 0.85)
    MASTERED = "mastered"  # 熟练 (> 0.85)


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    CHALLENGE = "challenge"


class GuidanceLevel(str, Enum):
    """How much guidance the student needs."""

    FULL = "full"  # 完全引导：从基础概念开始
    MODERATE = "moderate"  # 适度引导：给提示让学生尝试
    MINIMAL = "minimal"  # 最少引导：只在关键点提问
    VERIFY_ONLY = "verify_only"  # 仅验证：学生自己做，AI 只检查


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Graph
# ─────────────────────────────────────────────────────────────────────────────


class ExampleTemplate(BaseModel):
    """题目模板：含占位符的模板文本，用于练习生成。"""

    model_config = ConfigDict(extra="ignore")

    template_text: str
    variable_ranges: dict[str, Any] = Field(default_factory=dict)
    solution_template: str = ""
    difficulty: int = Field(ge=1, le=5, default=3)


class KnowledgePoint(BaseModel):
    """A single knowledge point in the curriculum."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    name_en: str = ""
    grade: int  # 7, 8, 9
    semester: Semester
    chapter: int
    section: int = 0
    textbook: Textbook = Textbook.RENJIAOBAN
    prerequisites: list[str] = Field(default_factory=list)
    difficulty: int = Field(ge=1, le=5, default=1)  # 1-5
    curriculum_requirement: str = ""  # 了解/理解/掌握/运用
    key_concepts: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    example_templates: list[ExampleTemplate] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class KnowledgeGraph(BaseModel):
    """Complete knowledge graph for a subject/grade."""

    model_config = ConfigDict(extra="ignore")

    subject: str = "math"
    grade: int = 7
    textbook: Textbook = Textbook.RENJIAOBAN
    points: list[KnowledgePoint] = Field(default_factory=list)

    def get_point(self, point_id: str) -> KnowledgePoint | None:
        for p in self.points:
            if p.id == point_id:
                return p
        return None

    def get_prerequisites(self, point_id: str) -> list[KnowledgePoint]:
        """Get all prerequisite knowledge points for a given point."""
        point = self.get_point(point_id)
        if not point:
            return []
        return [p for p in self.points if p.id in point.prerequisites]

    def get_points_for_chapter(self, grade: int, semester: Semester, chapter: int) -> list[KnowledgePoint]:
        return [
            p for p in self.points
            if p.grade == grade and p.semester == semester and p.chapter == chapter
        ]

    def get_next_points(self, mastered_ids: set[str]) -> list[KnowledgePoint]:
        """Find knowledge points whose prerequisites are all mastered."""
        candidates = []
        for p in self.points:
            if p.id in mastered_ids:
                continue
            if all(prereq in mastered_ids for prereq in p.prerequisites):
                candidates.append(p)
        return candidates


# ─────────────────────────────────────────────────────────────────────────────
# Student Profile
# ─────────────────────────────────────────────────────────────────────────────


class ProblemAttempt(BaseModel):
    """Record of a single problem attempt."""

    model_config = ConfigDict(extra="ignore")

    knowledge_point_id: str
    problem_summary: str = ""
    correct: bool = False
    guidance_level: GuidanceLevel = GuidanceLevel.MODERATE
    mistakes: list[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)


class StudentProfile(BaseModel):
    """Persistent student learning profile."""

    model_config = ConfigDict(extra="ignore")

    student_id: str
    name: str = ""
    grade: int = 7
    semester: Semester = Semester.UP
    textbook: Textbook = Textbook.RENJIAOBAN
    current_chapter: int = 1

    # Knowledge point mastery scores (0.0 ~ 1.0)
    mastery: dict[str, float] = Field(default_factory=dict)

    # Recent weak points (ordered, most recent first)
    weak_points: list[str] = Field(default_factory=list)

    # Problem attempt history (last N attempts)
    recent_attempts: list[ProblemAttempt] = Field(default_factory=list)

    # Streak tracking for difficulty adjustment
    streak_correct: int = 0
    streak_wrong: int = 0

    # Preferences
    preferred_language: str = "zh"

    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def get_mastery_level(self, point_id: str) -> MasteryLevel:
        score = self.mastery.get(point_id, 0.0)
        if score <= 0.0:
            return MasteryLevel.NOT_STARTED
        if score < 0.3:
            return MasteryLevel.BEGINNER
        if score < 0.6:
            return MasteryLevel.DEVELOPING
        if score < 0.85:
            return MasteryLevel.PROFICIENT
        return MasteryLevel.MASTERED

    def get_guidance_level(self, point_id: str) -> GuidanceLevel:
        """Determine how much guidance to provide based on mastery."""
        level = self.get_mastery_level(point_id)
        mapping = {
            MasteryLevel.NOT_STARTED: GuidanceLevel.FULL,
            MasteryLevel.BEGINNER: GuidanceLevel.FULL,
            MasteryLevel.DEVELOPING: GuidanceLevel.MODERATE,
            MasteryLevel.PROFICIENT: GuidanceLevel.MINIMAL,
            MasteryLevel.MASTERED: GuidanceLevel.VERIFY_ONLY,
        }
        return mapping[level]

    def update_mastery(self, point_id: str, correct: bool) -> None:
        """Update mastery score based on problem result."""
        current = self.mastery.get(point_id, 0.5)
        if correct:
            # Diminishing returns as mastery increases
            gain = 0.1 * (1.0 - current)
            self.mastery[point_id] = min(1.0, current + max(gain, 0.03))
            self.streak_correct += 1
            self.streak_wrong = 0
            # Remove from weak points if mastery is now sufficient
            if self.mastery[point_id] >= 0.7 and point_id in self.weak_points:
                self.weak_points.remove(point_id)
        else:
            self.mastery[point_id] = max(0.0, current - 0.12)
            self.streak_wrong += 1
            self.streak_correct = 0
            if point_id not in self.weak_points:
                self.weak_points.insert(0, point_id)
            # Keep only top 10 weak points
            self.weak_points = self.weak_points[:10]

        self.updated_at = time.time()

    def record_attempt(self, attempt: ProblemAttempt) -> None:
        """Record a problem attempt and update mastery."""
        self.recent_attempts.insert(0, attempt)
        # Keep last 50 attempts
        self.recent_attempts = self.recent_attempts[:50]
        self.update_mastery(attempt.knowledge_point_id, attempt.correct)

    def get_suggested_difficulty(self) -> Difficulty:
        """Suggest next problem difficulty based on recent performance."""
        if self.streak_correct >= 4:
            return Difficulty.HARD
        if self.streak_correct >= 2:
            return Difficulty.MEDIUM
        if self.streak_wrong >= 3:
            return Difficulty.EASY
        return Difficulty.MEDIUM


# ─────────────────────────────────────────────────────────────────────────────
# Teaching Strategy
# ─────────────────────────────────────────────────────────────────────────────


class GuidanceStep(BaseModel):
    """A single step in a guidance strategy."""

    model_config = ConfigDict(extra="ignore")

    ask: str  # Question to ask the student
    expect: str = ""  # Expected answer pattern
    if_wrong: str = ""  # Hint if student answers incorrectly
    if_stuck: str = ""  # Additional help if student is stuck


class CommonMistake(BaseModel):
    """A common mistake pattern and how to address it."""

    model_config = ConfigDict(extra="ignore")

    pattern: str  # Description of the mistake
    detection_hint: str = ""  # How to detect this mistake
    correction: str = ""  # How to guide correction


class TeachingStrategy(BaseModel):
    """Teaching strategy for a specific knowledge point and level."""

    model_config = ConfigDict(extra="ignore")

    knowledge_point_id: str
    guidance_level: GuidanceLevel
    steps: list[GuidanceStep] = Field(default_factory=list)
    common_mistakes: list[CommonMistake] = Field(default_factory=list)
    key_principles: list[str] = Field(default_factory=list)
    encouragement_phrases: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Completion & Mastery (for guided tutoring)
# ─────────────────────────────────────────────────────────────────────────────


class CompletionType(str, Enum):
    """How the student completed a problem step."""

    INDEPENDENT = "independent"  # 独立完成
    GUIDED = "guided"  # 引导完成
    FAILED = "failed"  # 未能完成


class MasteryRecord(BaseModel):
    """单个知识点的掌握记录。"""

    model_config = ConfigDict(extra="ignore")

    knowledge_point_id: str
    score: float = Field(ge=0.0, le=1.0, default=0.0)
    last_updated: float = 0.0
    attempt_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Student Profile Data (for guided tutoring persistence)
# ─────────────────────────────────────────────────────────────────────────────


class StudentProfileData(BaseModel):
    """学生画像数据（用于引导式辅导持久化）。"""

    model_config = ConfigDict(extra="ignore")

    student_id: str
    grade: str
    semester: str
    textbook_version: str
    mastery: dict[str, MasteryRecord] = Field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0


class LearningReport(BaseModel):
    """学习报告：按掌握度排列的知识点列表及薄弱项标记。"""

    model_config = ConfigDict(extra="ignore")

    student_id: str
    knowledge_points: list[MasteryRecord]
    weak_points: list[str]
    total_points: int
    average_mastery: float


# ─────────────────────────────────────────────────────────────────────────────
# Practice Problem
# ─────────────────────────────────────────────────────────────────────────────


class PracticeProblem(BaseModel):
    """练习题：包含题目文本、知识点、难度和参考答案。"""

    model_config = ConfigDict(extra="ignore")

    problem_text: str
    knowledge_points: list[str]
    difficulty: int = Field(ge=1, le=5)
    reference_answer: str
    category: Literal["weak", "review", "challenge"] = "weak"


# ─────────────────────────────────────────────────────────────────────────────
# Solving Session State
# ─────────────────────────────────────────────────────────────────────────────


class SolvingSessionState(BaseModel):
    """解题会话状态（序列化到 conversation metadata）。"""

    model_config = ConfigDict(extra="ignore")

    problem_text: str = ""
    analysis_result: dict[str, Any] = Field(default_factory=dict)
    current_step: int = 0
    total_steps: int = 0
    completed_steps: list[int] = Field(default_factory=list)
    error_count: dict[str, int] = Field(default_factory=dict)
    guidance_level: str = "full"
    steps: list[dict[str, Any]] = Field(default_factory=list)
    independent_steps: list[int] = Field(default_factory=list)
    is_complete: bool = False
    is_abandoned: bool = False
