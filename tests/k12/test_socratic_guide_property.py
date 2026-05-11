# Feature: k12-math-guided-tutoring, Property 2: 掌握度到引导等级的映射正确性
# Feature: k12-math-guided-tutoring, Property 3: 连续错误触发引导等级降低
"""
Property-based tests for SocraticGuide:
- Guidance level mapping from mastery scores (Property 2)
- Consecutive error downgrade behavior (Property 3)

Uses pytest + Hypothesis.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from deeptutor.k12.agents.socratic_guide import (
    GuidanceLevel,
    GuidanceState,
    GuidanceStep,
    SocraticGuide,
)
from deeptutor.k12.knowledge_graph import KnowledgeGraph, KnowledgePointNode
from deeptutor.k12.student_profile import StudentProfileService


# --- Helpers ---


def _make_test_kg():
    kg = KnowledgeGraph()
    for nid in ["kp_a", "kp_b"]:
        kg._nodes[nid] = KnowledgePointNode(
            id=nid, name=f"知识点{nid}", grade="7", semester="1", chapter="1", difficulty=1
        )
        kg._edges[nid] = []
    return kg


def _make_guide() -> SocraticGuide:
    kg = _make_test_kg()
    profile_service = StudentProfileService(storage_dir=None)
    return SocraticGuide(kg, profile_service)


# --- Property 2: 掌握度到引导等级的映射正确性 ---


@given(score=st.floats(min_value=0.0, max_value=1.0))
@settings(max_examples=100)
def test_single_score_guidance_level_mapping(score: float):
    """
    Property 2: For any single mastery score in [0.0, 1.0],
    determine_guidance_level should return:
    - FULL if score < 0.4
    - MODERATE if 0.4 <= score <= 0.7
    - MINIMAL if score > 0.7

    **Validates: Requirements 3.1**
    """
    guide = _make_guide()
    level = guide.determine_guidance_level([score])

    if score < 0.4:
        assert level == GuidanceLevel.FULL, (
            f"Score {score} < 0.4 should map to FULL, got {level}"
        )
    elif score <= 0.7:
        assert level == GuidanceLevel.MODERATE, (
            f"Score {score} in [0.4, 0.7] should map to MODERATE, got {level}"
        )
    else:
        assert level == GuidanceLevel.MINIMAL, (
            f"Score {score} > 0.7 should map to MINIMAL, got {level}"
        )


@given(scores=st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=10))
@settings(max_examples=100)
def test_multiple_scores_guidance_level_mapping(scores: list[float]):
    """
    Property 2: For any list of mastery scores, the average determines
    the guidance level using the same thresholds.

    **Validates: Requirements 3.1**
    """
    guide = _make_guide()
    level = guide.determine_guidance_level(scores)

    avg = sum(scores) / len(scores)

    if avg < 0.4:
        assert level == GuidanceLevel.FULL, (
            f"Average {avg} < 0.4 should map to FULL, got {level}"
        )
    elif avg <= 0.7:
        assert level == GuidanceLevel.MODERATE, (
            f"Average {avg} in [0.4, 0.7] should map to MODERATE, got {level}"
        )
    else:
        assert level == GuidanceLevel.MINIMAL, (
            f"Average {avg} > 0.7 should map to MINIMAL, got {level}"
        )


# --- Property 3: 连续错误触发引导等级降低 ---


@given(initial_level=st.sampled_from(GuidanceLevel))
@settings(max_examples=100)
def test_consecutive_error_downgrade(initial_level: GuidanceLevel):
    """
    Property 3: When error_count reaches 3 on a step, the guidance level
    should downgrade:
    - MINIMAL → MODERATE
    - MODERATE → FULL
    - FULL → FULL (stays, cannot go lower)

    **Validates: Requirements 3.6**
    """
    guide = _make_guide()

    # Create a state with the given initial level and 3 errors on step 0
    state = GuidanceState(
        current_step=0,
        total_steps=2,
        guidance_level=initial_level,
        error_count={0: 3},
        steps=[
            GuidanceStep(
                step_index=0,
                question="test question",
                hint="test hint",
                expected_direction="test direction",
                knowledge_point_id="kp_a",
            ),
            GuidanceStep(
                step_index=1,
                question="test question 2",
                hint="test hint 2",
                expected_direction="test direction 2",
                knowledge_point_id="kp_b",
            ),
        ],
    )

    new_level = guide.downgrade_guidance(state, step_index=0)

    if initial_level == GuidanceLevel.MINIMAL:
        assert new_level == GuidanceLevel.MODERATE, (
            f"MINIMAL should downgrade to MODERATE, got {new_level}"
        )
    elif initial_level == GuidanceLevel.MODERATE:
        assert new_level == GuidanceLevel.FULL, (
            f"MODERATE should downgrade to FULL, got {new_level}"
        )
    else:
        # FULL stays at FULL
        assert new_level == GuidanceLevel.FULL, (
            f"FULL should stay at FULL, got {new_level}"
        )
