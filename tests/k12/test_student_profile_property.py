# Feature: k12-math-guided-tutoring, Property 5: 掌握度更新公式与边界约束
# Feature: k12-math-guided-tutoring, Property 4: 学生画像持久化往返一致性
# Feature: k12-math-guided-tutoring, Property 6: 学习报告按掌握度升序排列且正确标记薄弱项
"""
Property-based tests for StudentProfileService.

Tests cover:
- Property 5: Mastery update formula and boundary constraints
- Property 4: Profile persistence roundtrip consistency
- Property 6: Learning report sorted ascending by score with correct weak point marking
"""

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from deeptutor.k12.knowledge_graph import KnowledgeGraph, KnowledgePointNode
from deeptutor.k12.models import (
    CompletionType,
    LearningReport,
    MasteryRecord,
    StudentProfileData,
)
from deeptutor.k12.student_profile import StudentProfileService


# ─── Strategies ──────────────────────────────────────────────────────────────

# Strategy for mastery scores in valid range
mastery_score_st = st.floats(min_value=0.0, max_value=1.0)

# Strategy for CompletionType
completion_type_st = st.sampled_from(list(CompletionType))

# Strategy for knowledge point IDs
knowledge_point_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_.-"),
    min_size=1,
    max_size=30,
)

# Strategy for generating random mastery records
@st.composite
def mastery_record_strategy(draw):
    point_id = draw(knowledge_point_id_st)
    score = draw(mastery_score_st)
    last_updated = draw(st.floats(min_value=0.0, max_value=2000000000.0))
    attempt_count = draw(st.integers(min_value=0, max_value=1000))
    return point_id, MasteryRecord(
        knowledge_point_id=point_id,
        score=score,
        last_updated=last_updated,
        attempt_count=attempt_count,
    )


# Strategy for generating valid StudentProfileData
@st.composite
def student_profile_data_strategy(draw):
    student_id = draw(st.text(min_size=1, max_size=20, alphabet=st.characters(
        whitelist_categories=("L", "N"), whitelist_characters="_-"
    )))
    grade = draw(st.sampled_from(["7", "8", "9"]))
    semester = draw(st.sampled_from(["1", "2"]))
    textbook_version = draw(st.text(min_size=1, max_size=20))

    # Generate random mastery records
    num_records = draw(st.integers(min_value=0, max_value=10))
    mastery: dict[str, MasteryRecord] = {}
    for _ in range(num_records):
        point_id, record = draw(mastery_record_strategy())
        mastery[point_id] = record

    created_at = draw(st.floats(min_value=0.0, max_value=2000000000.0))
    updated_at = draw(st.floats(min_value=created_at, max_value=2000000000.0))

    return StudentProfileData(
        student_id=student_id,
        grade=grade,
        semester=semester,
        textbook_version=textbook_version,
        mastery=mastery,
        created_at=created_at,
        updated_at=updated_at,
    )


# ─── Property 5: 掌握度更新公式与边界约束 ────────────────────────────────────


@given(current_score=mastery_score_st, completion_type=completion_type_st)
@settings(max_examples=100)
def test_mastery_update_formula_and_boundary(
    current_score: float, completion_type: CompletionType
):
    """
    Property 5: For any current mastery score in [0.0, 1.0] and any CompletionType,
    update_mastery applies the correct delta and clamps result to [0.0, 1.0].

    - INDEPENDENT: new_score = clamp(score + 0.15, 0.0, 1.0)
    - GUIDED: new_score = clamp(score + 0.08, 0.0, 1.0)
    - FAILED: new_score = clamp(score - 0.05, 0.0, 1.0)

    **Validates: Requirements 5.3, 5.4**
    """
    # Setup: create a profile with a single knowledge point at the given score
    point_id = "test_point"
    profile = StudentProfileData(
        student_id="test_student",
        grade="7",
        semester="1",
        textbook_version="人教版",
        mastery={
            point_id: MasteryRecord(
                knowledge_point_id=point_id,
                score=current_score,
                last_updated=0.0,
                attempt_count=0,
            )
        },
    )

    service = StudentProfileService(storage_dir=Path("/tmp/test_profiles"))
    new_score = service.update_mastery(profile, point_id, completion_type)

    # Compute expected score
    deltas = {
        CompletionType.INDEPENDENT: 0.15,
        CompletionType.GUIDED: 0.08,
        CompletionType.FAILED: -0.05,
    }
    expected = max(0.0, min(1.0, current_score + deltas[completion_type]))

    # Verify formula correctness
    assert abs(new_score - expected) < 1e-9, (
        f"Expected {expected}, got {new_score} "
        f"(current={current_score}, type={completion_type})"
    )

    # Verify boundary constraint: result always in [0.0, 1.0]
    assert 0.0 <= new_score <= 1.0, (
        f"Score {new_score} out of bounds [0.0, 1.0]"
    )


# ─── Property 4: 学生画像持久化往返一致性 ─────────────────────────────────────


@given(profile=student_profile_data_strategy())
@settings(max_examples=100)
def test_profile_persistence_roundtrip(profile: StudentProfileData):
    """
    Property 4: For any valid StudentProfileData, save_profile then load_profile
    should return an object equivalent to the original (except updated_at which
    is refreshed on save).

    **Validates: Requirements 5.2**
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_dir = Path(tmp_dir)
        service = StudentProfileService(storage_dir=storage_dir)

        # Save the profile
        service.save_profile(profile)

        # Load it back
        loaded = service.load_profile(profile.student_id)

        # Must not be None
        assert loaded is not None, "Profile should be loadable after save"

        # Core fields must match exactly
        assert loaded.student_id == profile.student_id
        assert loaded.grade == profile.grade
        assert loaded.semester == profile.semester
        assert loaded.textbook_version == profile.textbook_version
        assert loaded.created_at == profile.created_at

        # Mastery records must match
        assert set(loaded.mastery.keys()) == set(profile.mastery.keys())
        for point_id, record in profile.mastery.items():
            loaded_record = loaded.mastery[point_id]
            assert loaded_record.knowledge_point_id == record.knowledge_point_id
            assert abs(loaded_record.score - record.score) < 1e-9
            assert loaded_record.last_updated == record.last_updated
            assert loaded_record.attempt_count == record.attempt_count


# ─── Property 6: 学习报告按掌握度升序排列且正确标记薄弱项 ─────────────────────


@given(profile=student_profile_data_strategy())
@settings(max_examples=100)
def test_learning_report_sorted_and_weak_points(profile: StudentProfileData):
    """
    Property 6: For any StudentProfileData with random mastery scores:
    - get_learning_report returns knowledge_points sorted by score ascending
    - All points with score < 0.4 are in weak_points
    - No points with score >= 0.4 are in weak_points

    **Validates: Requirements 5.5**
    """
    service = StudentProfileService(storage_dir=Path("/tmp/test_profiles"))
    report: LearningReport = service.get_learning_report(profile)

    # Verify sorted ascending by score
    scores = [record.score for record in report.knowledge_points]
    for i in range(len(scores) - 1):
        assert scores[i] <= scores[i + 1], (
            f"Knowledge points not sorted ascending: "
            f"score[{i}]={scores[i]} > score[{i+1}]={scores[i+1]}"
        )

    # Verify weak_points contains exactly those with score < 0.4
    weak_set = set(report.weak_points)
    for record in report.knowledge_points:
        if record.score < 0.4:
            assert record.knowledge_point_id in weak_set, (
                f"Point {record.knowledge_point_id} with score {record.score} "
                f"should be in weak_points"
            )
        else:
            assert record.knowledge_point_id not in weak_set, (
                f"Point {record.knowledge_point_id} with score {record.score} "
                f"should NOT be in weak_points"
            )

    # Verify total_points matches
    assert report.total_points == len(profile.mastery)

    # Verify student_id matches
    assert report.student_id == profile.student_id
