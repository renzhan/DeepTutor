"""
Student Profile Service
=======================

Manages student learning profiles with JSON file persistence.
Provides mastery score updates and learning report generation.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from deeptutor.k12.knowledge_graph import KnowledgeGraph
from deeptutor.k12.models import (
    CompletionType,
    LearningReport,
    MasteryRecord,
    StudentProfileData,
)

logger = logging.getLogger(__name__)


# Mastery update increments per completion type
_MASTERY_DELTAS = {
    CompletionType.INDEPENDENT: 0.15,
    CompletionType.GUIDED: 0.08,
    CompletionType.FAILED: -0.05,
}


class StudentProfileService:
    """
    Student profile manager with JSON file persistence.

    Usage::

        service = StudentProfileService(storage_dir=Path("./profiles"))
        profile = service.create_profile("student_001", "7", "1", "人教版", kg)
        new_score = service.update_mastery(
            profile, "rational_numbers.concept", CompletionType.INDEPENDENT
        )
        service.save_profile(profile)
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or Path("./student_profiles")

    # ─── Profile Lifecycle ───────────────────────────────────────────────

    def create_profile(
        self,
        student_id: str,
        grade: str,
        semester: str,
        textbook_version: str,
        knowledge_graph: KnowledgeGraph,
    ) -> StudentProfileData:
        """Create a new student profile with all mastery scores initialized to 0.0."""
        now = time.time()
        mastery: dict[str, MasteryRecord] = {}
        for point_id in knowledge_graph.node_ids:
            mastery[point_id] = MasteryRecord(
                knowledge_point_id=point_id,
                score=0.0,
                last_updated=now,
                attempt_count=0,
            )
        profile = StudentProfileData(
            student_id=student_id,
            grade=grade,
            semester=semester,
            textbook_version=textbook_version,
            mastery=mastery,
            created_at=now,
            updated_at=now,
        )
        return profile

    def load_profile(self, student_id: str) -> StudentProfileData | None:
        """Load a student profile from JSON file. Returns None if not found."""
        filepath = self._get_filepath(student_id)
        if not filepath.exists():
            return None
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            return StudentProfileData.model_validate(data)
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to load profile %s: %s", student_id, exc)
            return None

    def save_profile(self, profile: StudentProfileData) -> None:
        """Persist student profile to JSON file."""
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._get_filepath(profile.student_id)
        profile.updated_at = time.time()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(profile.model_dump_json(indent=2))

    # ─── Mastery Updates ─────────────────────────────────────────────────

    def update_mastery(
        self,
        profile: StudentProfileData,
        knowledge_point_id: str,
        completion_type: CompletionType,
    ) -> float:
        """
        Update mastery score for a knowledge point.

        Rules:
        - INDEPENDENT: +0.15
        - GUIDED: +0.08
        - FAILED: -0.05

        Result is clamped to [0.0, 1.0].
        Returns the new score.
        """
        delta = _MASTERY_DELTAS[completion_type]

        if knowledge_point_id not in profile.mastery:
            profile.mastery[knowledge_point_id] = MasteryRecord(
                knowledge_point_id=knowledge_point_id,
                score=0.0,
                last_updated=time.time(),
                attempt_count=0,
            )

        record = profile.mastery[knowledge_point_id]
        new_score = max(0.0, min(1.0, record.score + delta))
        record.score = new_score
        record.last_updated = time.time()
        record.attempt_count += 1
        profile.updated_at = time.time()

        return new_score

    # ─── Reporting ───────────────────────────────────────────────────────

    def get_learning_report(self, profile: StudentProfileData) -> LearningReport:
        """
        Generate learning report.

        - Knowledge points sorted by score ascending
        - Weak points: score < 0.4
        """
        records = list(profile.mastery.values())
        sorted_records = sorted(records, key=lambda r: r.score)
        weak_points = [r.knowledge_point_id for r in sorted_records if r.score < 0.4]
        total = len(sorted_records)
        avg = sum(r.score for r in sorted_records) / total if total > 0 else 0.0

        return LearningReport(
            student_id=profile.student_id,
            knowledge_points=sorted_records,
            weak_points=weak_points,
            total_points=total,
            average_mastery=avg,
        )

    # ─── Internal ────────────────────────────────────────────────────────

    def _get_filepath(self, student_id: str) -> Path:
        """Get the JSON file path for a student profile."""
        return self._storage_dir / f"{student_id}.json"
