"""
Unit tests for StudentProfileService module.

Tests cover:
- Profile creation with knowledge graph initialization
- Profile persistence (save/load)
- Mastery update rules (INDEPENDENT, GUIDED, FAILED)
- Score clamping to [0.0, 1.0]
- Learning report generation

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

import json
import tempfile
from pathlib import Path

import pytest

from deeptutor.k12.knowledge_graph import KnowledgeGraph, KnowledgePointNode
from deeptutor.k12.models import CompletionType, MasteryRecord, StudentProfileData
from deeptutor.k12.student_profile import StudentProfileService


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_kg() -> KnowledgeGraph:
    """Create a small knowledge graph with 3 nodes for testing."""
    kg = KnowledgeGraph()
    for node_id in ["point_a", "point_b", "point_c"]:
        kg._nodes[node_id] = KnowledgePointNode(
            id=node_id,
            name=f"Node {node_id}",
            grade="7",
            semester="1",
            chapter="Ch1",
            difficulty=1,
            prerequisites=[],
        )
        kg._edges[node_id] = []
    return kg


@pytest.fixture
def tmp_storage(tmp_path: Path) -> Path:
    """Provide a temporary directory for profile storage."""
    return tmp_path / "profiles"


@pytest.fixture
def service(tmp_storage: Path) -> StudentProfileService:
    """Create a StudentProfileService with temporary storage."""
    return StudentProfileService(storage_dir=tmp_storage)


@pytest.fixture
def sample_profile(service: StudentProfileService, sample_kg: KnowledgeGraph) -> StudentProfileData:
    """Create a sample profile for testing."""
    return service.create_profile("student_001", "7", "1", "人教版", sample_kg)


# ─────────────────────────────────────────────────────────────────────────────
# create_profile
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateProfile:
    """Test profile creation with knowledge graph initialization."""

    def test_creates_profile_with_correct_metadata(
        self, service: StudentProfileService, sample_kg: KnowledgeGraph
    ):
        """Test that create_profile sets student_id, grade, semester, textbook."""
        profile = service.create_profile("s1", "8", "2", "北师大版", sample_kg)
        assert profile.student_id == "s1"
        assert profile.grade == "8"
        assert profile.semester == "2"
        assert profile.textbook_version == "北师大版"

    def test_initializes_all_knowledge_points_to_zero(
        self, service: StudentProfileService, sample_kg: KnowledgeGraph
    ):
        """Test that all knowledge points start with mastery score 0.0."""
        profile = service.create_profile("s1", "7", "1", "人教版", sample_kg)
        assert len(profile.mastery) == 3
        for record in profile.mastery.values():
            assert record.score == 0.0
            assert record.attempt_count == 0

    def test_mastery_keys_match_knowledge_graph_nodes(
        self, service: StudentProfileService, sample_kg: KnowledgeGraph
    ):
        """Test that mastery dict keys match the knowledge graph node IDs."""
        profile = service.create_profile("s1", "7", "1", "人教版", sample_kg)
        assert set(profile.mastery.keys()) == {"point_a", "point_b", "point_c"}

    def test_timestamps_are_set(
        self, service: StudentProfileService, sample_kg: KnowledgeGraph
    ):
        """Test that created_at and updated_at are set to non-zero values."""
        profile = service.create_profile("s1", "7", "1", "人教版", sample_kg)
        assert profile.created_at > 0
        assert profile.updated_at > 0


# ─────────────────────────────────────────────────────────────────────────────
# save_profile and load_profile
# ─────────────────────────────────────────────────────────────────────────────


class TestPersistence:
    """Test JSON file persistence (save and load)."""

    def test_save_and_load_roundtrip(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that saving and loading a profile preserves all data."""
        service.save_profile(sample_profile)
        loaded = service.load_profile("student_001")
        assert loaded is not None
        assert loaded.student_id == sample_profile.student_id
        assert loaded.grade == sample_profile.grade
        assert loaded.semester == sample_profile.semester
        assert loaded.textbook_version == sample_profile.textbook_version
        assert len(loaded.mastery) == len(sample_profile.mastery)

    def test_load_nonexistent_returns_none(self, service: StudentProfileService):
        """Test that loading a non-existent profile returns None."""
        result = service.load_profile("nonexistent_student")
        assert result is None

    def test_save_creates_storage_directory(
        self, tmp_path: Path, sample_profile: StudentProfileData
    ):
        """Test that save_profile creates the storage directory if it doesn't exist."""
        new_dir = tmp_path / "new_dir" / "nested"
        svc = StudentProfileService(storage_dir=new_dir)
        svc.save_profile(sample_profile)
        assert new_dir.exists()

    def test_load_corrupted_file_returns_none(self, tmp_storage: Path):
        """Test that loading a corrupted JSON file returns None."""
        tmp_storage.mkdir(parents=True, exist_ok=True)
        corrupted_file = tmp_storage / "bad_student.json"
        corrupted_file.write_text("{invalid json content!!!", encoding="utf-8")

        svc = StudentProfileService(storage_dir=tmp_storage)
        result = svc.load_profile("bad_student")
        assert result is None

    def test_mastery_scores_preserved_after_roundtrip(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that mastery scores are preserved through save/load."""
        # Update a score before saving
        service.update_mastery(sample_profile, "point_a", CompletionType.INDEPENDENT)
        service.save_profile(sample_profile)

        loaded = service.load_profile("student_001")
        assert loaded is not None
        assert abs(loaded.mastery["point_a"].score - 0.15) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# update_mastery
# ─────────────────────────────────────────────────────────────────────────────


class TestUpdateMastery:
    """Test mastery score update rules."""

    def test_independent_adds_015(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test INDEPENDENT completion adds +0.15."""
        score = service.update_mastery(sample_profile, "point_a", CompletionType.INDEPENDENT)
        assert abs(score - 0.15) < 0.001

    def test_guided_adds_008(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test GUIDED completion adds +0.08."""
        score = service.update_mastery(sample_profile, "point_a", CompletionType.GUIDED)
        assert abs(score - 0.08) < 0.001

    def test_failed_subtracts_005(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test FAILED completion subtracts -0.05 (clamped to 0.0 from initial 0.0)."""
        score = service.update_mastery(sample_profile, "point_a", CompletionType.FAILED)
        assert score == 0.0

    def test_failed_from_nonzero(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test FAILED subtracts 0.05 from a non-zero score."""
        service.update_mastery(sample_profile, "point_a", CompletionType.INDEPENDENT)  # 0.15
        score = service.update_mastery(sample_profile, "point_a", CompletionType.FAILED)
        assert abs(score - 0.10) < 0.001

    def test_attempt_count_increments(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that attempt_count increments with each update."""
        service.update_mastery(sample_profile, "point_a", CompletionType.INDEPENDENT)
        service.update_mastery(sample_profile, "point_a", CompletionType.GUIDED)
        assert sample_profile.mastery["point_a"].attempt_count == 2

    def test_update_unknown_point_creates_record(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that updating a point not in mastery creates a new record."""
        score = service.update_mastery(sample_profile, "new_point", CompletionType.INDEPENDENT)
        assert abs(score - 0.15) < 0.001
        assert "new_point" in sample_profile.mastery


# ─────────────────────────────────────────────────────────────────────────────
# Score clamping
# ─────────────────────────────────────────────────────────────────────────────


class TestScoreClamping:
    """Test that mastery scores are clamped to [0.0, 1.0]."""

    def test_clamp_at_zero(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that score cannot go below 0.0."""
        # Multiple FAILED from 0.0 should stay at 0.0
        for _ in range(5):
            score = service.update_mastery(sample_profile, "point_a", CompletionType.FAILED)
        assert score == 0.0

    def test_clamp_at_one(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that score cannot exceed 1.0."""
        # 7 * 0.15 = 1.05, should clamp to 1.0
        for _ in range(10):
            score = service.update_mastery(sample_profile, "point_a", CompletionType.INDEPENDENT)
        assert score == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# get_learning_report
# ─────────────────────────────────────────────────────────────────────────────


class TestGetLearningReport:
    """Test learning report generation."""

    def test_report_contains_all_points(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that the report includes all knowledge points."""
        report = service.get_learning_report(sample_profile)
        assert report.total_points == 3
        assert len(report.knowledge_points) == 3

    def test_report_sorted_ascending_by_score(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that knowledge_points are sorted by score ascending."""
        service.update_mastery(sample_profile, "point_a", CompletionType.INDEPENDENT)  # 0.15
        service.update_mastery(sample_profile, "point_b", CompletionType.GUIDED)  # 0.08
        # point_c stays at 0.0

        report = service.get_learning_report(sample_profile)
        scores = [r.score for r in report.knowledge_points]
        assert scores == sorted(scores)

    def test_weak_points_below_04(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that weak_points contains only points with score < 0.4."""
        # Make point_a mastery >= 0.4
        for _ in range(3):
            service.update_mastery(sample_profile, "point_a", CompletionType.INDEPENDENT)
        # point_a is now 0.45, point_b and point_c are 0.0

        report = service.get_learning_report(sample_profile)
        assert "point_a" not in report.weak_points
        assert "point_b" in report.weak_points
        assert "point_c" in report.weak_points

    def test_average_mastery_calculation(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that average_mastery is correctly calculated."""
        service.update_mastery(sample_profile, "point_a", CompletionType.INDEPENDENT)  # 0.15
        service.update_mastery(sample_profile, "point_b", CompletionType.GUIDED)  # 0.08
        # point_c = 0.0

        report = service.get_learning_report(sample_profile)
        expected_avg = (0.15 + 0.08 + 0.0) / 3
        assert abs(report.average_mastery - expected_avg) < 0.001

    def test_report_student_id(
        self, service: StudentProfileService, sample_profile: StudentProfileData
    ):
        """Test that the report has the correct student_id."""
        report = service.get_learning_report(sample_profile)
        assert report.student_id == "student_001"

    def test_empty_profile_report(self, service: StudentProfileService):
        """Test report generation for a profile with no mastery records."""
        profile = StudentProfileData(
            student_id="empty",
            grade="7",
            semester="1",
            textbook_version="人教版",
            mastery={},
        )
        report = service.get_learning_report(profile)
        assert report.total_points == 0
        assert report.average_mastery == 0.0
        assert report.weak_points == []
