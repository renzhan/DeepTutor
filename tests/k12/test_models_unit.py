"""
Unit tests for K12 data models.

Tests cover:
- KnowledgePoint field validation (difficulty range, required fields)
- MasteryRecord score boundary constraints
- SolvingSessionState JSON serialization/deserialization

Requirements: 5.4, 6.1, 8.1
"""

import pytest
from pydantic import ValidationError

from deeptutor.k12.models import (
    KnowledgePoint,
    MasteryRecord,
    Semester,
    SolvingSessionState,
)


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgePoint field validation
# ─────────────────────────────────────────────────────────────────────────────


class TestKnowledgePointValidation:
    """Test KnowledgePoint field validation (difficulty range, required fields)."""

    def _valid_kwargs(self, **overrides):
        """Return minimal valid kwargs for KnowledgePoint."""
        defaults = {
            "id": "kp_001",
            "name": "有理数加法",
            "grade": 7,
            "semester": Semester.UP,
            "chapter": 1,
        }
        defaults.update(overrides)
        return defaults

    def test_difficulty_min_valid(self):
        """Test creating KnowledgePoint with difficulty=1 succeeds."""
        kp = KnowledgePoint(**self._valid_kwargs(difficulty=1))
        assert kp.difficulty == 1

    def test_difficulty_max_valid(self):
        """Test creating KnowledgePoint with difficulty=5 succeeds."""
        kp = KnowledgePoint(**self._valid_kwargs(difficulty=5))
        assert kp.difficulty == 5

    def test_difficulty_below_min_raises(self):
        """Test creating KnowledgePoint with difficulty=0 raises ValidationError."""
        with pytest.raises(ValidationError):
            KnowledgePoint(**self._valid_kwargs(difficulty=0))

    def test_difficulty_above_max_raises(self):
        """Test creating KnowledgePoint with difficulty=6 raises ValidationError."""
        with pytest.raises(ValidationError):
            KnowledgePoint(**self._valid_kwargs(difficulty=6))

    def test_required_field_id(self):
        """Test that 'id' field must be provided."""
        kwargs = self._valid_kwargs()
        del kwargs["id"]
        with pytest.raises(ValidationError):
            KnowledgePoint(**kwargs)

    def test_required_field_name(self):
        """Test that 'name' field must be provided."""
        kwargs = self._valid_kwargs()
        del kwargs["name"]
        with pytest.raises(ValidationError):
            KnowledgePoint(**kwargs)

    def test_required_field_grade(self):
        """Test that 'grade' field must be provided."""
        kwargs = self._valid_kwargs()
        del kwargs["grade"]
        with pytest.raises(ValidationError):
            KnowledgePoint(**kwargs)

    def test_required_field_semester(self):
        """Test that 'semester' field must be provided."""
        kwargs = self._valid_kwargs()
        del kwargs["semester"]
        with pytest.raises(ValidationError):
            KnowledgePoint(**kwargs)

    def test_required_field_chapter(self):
        """Test that 'chapter' field must be provided."""
        kwargs = self._valid_kwargs()
        del kwargs["chapter"]
        with pytest.raises(ValidationError):
            KnowledgePoint(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# MasteryRecord score boundary constraints
# ─────────────────────────────────────────────────────────────────────────────


class TestMasteryRecordScoreBoundary:
    """Test MasteryRecord score boundary constraints."""

    def test_score_zero_valid(self):
        """Test creating MasteryRecord with score=0.0 succeeds."""
        record = MasteryRecord(knowledge_point_id="kp_001", score=0.0)
        assert record.score == 0.0

    def test_score_one_valid(self):
        """Test creating MasteryRecord with score=1.0 succeeds."""
        record = MasteryRecord(knowledge_point_id="kp_001", score=1.0)
        assert record.score == 1.0

    def test_score_mid_valid(self):
        """Test creating MasteryRecord with score=0.5 succeeds."""
        record = MasteryRecord(knowledge_point_id="kp_001", score=0.5)
        assert record.score == 0.5

    def test_score_below_zero_raises(self):
        """Test creating MasteryRecord with score=-0.01 raises ValidationError."""
        with pytest.raises(ValidationError):
            MasteryRecord(knowledge_point_id="kp_001", score=-0.01)

    def test_score_above_one_raises(self):
        """Test creating MasteryRecord with score=1.01 raises ValidationError."""
        with pytest.raises(ValidationError):
            MasteryRecord(knowledge_point_id="kp_001", score=1.01)


# ─────────────────────────────────────────────────────────────────────────────
# SolvingSessionState JSON serialization/deserialization
# ─────────────────────────────────────────────────────────────────────────────


class TestSolvingSessionStateSerialization:
    """Test SolvingSessionState JSON serialization/deserialization."""

    def test_default_state_roundtrip(self):
        """Test serializing a default SolvingSessionState to JSON and back."""
        state = SolvingSessionState()
        json_str = state.model_dump_json()
        restored = SolvingSessionState.model_validate_json(json_str)
        assert restored == state

    def test_fully_populated_state_roundtrip(self):
        """Test serializing a fully populated SolvingSessionState to JSON and back."""
        state = SolvingSessionState(
            problem_text="求解方程 2x + 3 = 7",
            analysis_result={"knowledge_points": ["linear_eq"], "difficulty": 2},
            current_step=2,
            total_steps=4,
            completed_steps=[0, 1],
            error_count={"step_0": 1, "step_2": 3},
            guidance_level="moderate",
            steps=[
                {"ask": "移项", "expect": "2x = 4"},
                {"ask": "除以系数", "expect": "x = 2"},
            ],
            independent_steps=[0],
            is_complete=False,
            is_abandoned=False,
        )
        json_str = state.model_dump_json()
        restored = SolvingSessionState.model_validate_json(json_str)
        assert restored == state

    def test_all_fields_preserved_after_roundtrip(self):
        """Test that all fields are preserved after roundtrip."""
        state = SolvingSessionState(
            problem_text="计算 3 × 4 + 5",
            current_step=1,
            total_steps=2,
            completed_steps=[0],
            error_count={"step_1": 2},
            guidance_level="full",
            steps=[{"ask": "先算乘法", "expect": "12"}],
            independent_steps=[],
            is_complete=False,
            is_abandoned=False,
        )
        json_str = state.model_dump_json()
        restored = SolvingSessionState.model_validate_json(json_str)

        assert restored.problem_text == state.problem_text
        assert restored.current_step == state.current_step
        assert restored.total_steps == state.total_steps
        assert restored.completed_steps == state.completed_steps
        assert restored.error_count == state.error_count
        assert restored.guidance_level == state.guidance_level
        assert restored.steps == state.steps
        assert restored.independent_steps == state.independent_steps
        assert restored.is_complete == state.is_complete
        assert restored.is_abandoned == state.is_abandoned

    def test_error_count_dict_with_string_keys(self):
        """Test that error_count dict with string keys works correctly."""
        state = SolvingSessionState(
            error_count={"step_0": 1, "step_1": 0, "step_2": 3}
        )
        json_str = state.model_dump_json()
        restored = SolvingSessionState.model_validate_json(json_str)
        assert restored.error_count == {"step_0": 1, "step_1": 0, "step_2": 3}
