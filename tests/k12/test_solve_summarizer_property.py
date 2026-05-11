# Feature: k12-math-guided-tutoring, Property 13: 解题总结包含所有必要信息
"""
Property-based tests for SolveSummarizer:
- Solve summary contains all required information (Property 13)

Uses pytest + Hypothesis.

**Validates: Requirements 9.1, 9.2, 9.3**
"""

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from deeptutor.core.stream_bus import StreamBus
from deeptutor.k12.agents.problem_analyzer import AnalysisResult
from deeptutor.k12.agents.socratic_guide import GuidanceState, GuidanceStep
from deeptutor.k12.agents.solve_summarizer import SolveSummarizer
from deeptutor.k12.models import MasteryRecord, StudentProfileData
from deeptutor.k12.student_profile import StudentProfileService


# --- Strategies ---

# Generate knowledge point IDs
kp_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=3,
    max_size=15,
)


@st.composite
def guidance_step_strategy(draw, step_index: int, kp_id: str | None = None):
    """Generate a GuidanceStep with a given index."""
    if kp_id is None:
        kp_id = draw(kp_id_strategy)
    return GuidanceStep(
        step_index=step_index,
        question=draw(st.text(min_size=1, max_size=50)),
        hint=draw(st.text(min_size=1, max_size=50)),
        expected_direction=draw(st.text(min_size=1, max_size=50)),
        knowledge_point_id=kp_id,
    )


@st.composite
def completed_guidance_state_strategy(draw):
    """
    Generate a completed GuidanceState with all steps completed.
    Some steps are independent, some are not.
    """
    num_steps = draw(st.integers(min_value=1, max_value=6))

    # Generate unique knowledge point IDs for each step
    kp_ids = [draw(kp_id_strategy) for _ in range(num_steps)]

    steps = []
    for i in range(num_steps):
        step = GuidanceStep(
            step_index=i,
            question=f"question_{i}",
            hint=f"hint_{i}",
            expected_direction=f"direction_{i}",
            knowledge_point_id=kp_ids[i],
        )
        steps.append(step)

    # All steps are completed
    completed_steps = list(range(num_steps))

    # Some subset of steps are independent (randomly chosen)
    independent_steps = draw(
        st.lists(
            st.integers(min_value=0, max_value=num_steps - 1),
            min_size=0,
            max_size=num_steps,
            unique=True,
        )
    )

    return GuidanceState(
        current_step=num_steps,
        total_steps=num_steps,
        completed_steps=completed_steps,
        error_count={},
        steps=steps,
        independent_steps=sorted(independent_steps),
    )


@st.composite
def analysis_result_strategy(draw, kp_ids: list[str] | None = None):
    """Generate an AnalysisResult with given or random knowledge points."""
    if kp_ids is None:
        kp_ids = draw(st.lists(kp_id_strategy, min_size=1, max_size=5))
    return AnalysisResult(
        problem_text=draw(st.text(min_size=5, max_size=100)),
        knowledge_points=kp_ids,
        difficulty_estimate=draw(st.integers(min_value=1, max_value=5)),
        solution_steps=[f"step_{i}" for i in range(len(kp_ids))],
    )


def _make_profile(kp_ids: list[str]) -> StudentProfileData:
    """Create a StudentProfileData with mastery records for given kp_ids."""
    mastery = {}
    for kp_id in kp_ids:
        mastery[kp_id] = MasteryRecord(
            knowledge_point_id=kp_id,
            score=0.3,
            last_updated=0.0,
            attempt_count=0,
        )
    return StudentProfileData(
        student_id="test_student",
        grade="7",
        semester="1",
        textbook_version="人教版",
        mastery=mastery,
    )


# --- Property 13: 解题总结包含所有必要信息 ---


@given(state=completed_guidance_state_strategy())
@settings(max_examples=50)
def test_summary_response_is_non_empty(state: GuidanceState):
    """
    Property 13: For any completed GuidanceState, the summary response
    should be a non-empty string.

    **Validates: Requirements 9.1, 9.2, 9.3**
    """
    # Extract knowledge point IDs from steps
    kp_ids = [step.knowledge_point_id for step in state.steps]

    analysis = AnalysisResult(
        problem_text="测试题目",
        knowledge_points=kp_ids,
        difficulty_estimate=3,
        solution_steps=[f"step_{i}" for i in range(len(kp_ids))],
    )
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = asyncio.get_event_loop().run_until_complete(
        summarizer.summarize(state, analysis, profile, stream)
    )

    assert summary.response, "Summary response must be non-empty"
    assert len(summary.response) > 0


@given(state=completed_guidance_state_strategy())
@settings(max_examples=50)
def test_summary_knowledge_points_non_empty(state: GuidanceState):
    """
    Property 13: For any completed GuidanceState with steps,
    the summary knowledge_points list should be non-empty.

    **Validates: Requirements 9.1, 9.2, 9.3**
    """
    kp_ids = [step.knowledge_point_id for step in state.steps]

    analysis = AnalysisResult(
        problem_text="测试题目",
        knowledge_points=kp_ids,
        difficulty_estimate=3,
        solution_steps=[f"step_{i}" for i in range(len(kp_ids))],
    )
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = asyncio.get_event_loop().run_until_complete(
        summarizer.summarize(state, analysis, profile, stream)
    )

    assert len(summary.knowledge_points) > 0, "Knowledge points must be non-empty"


@given(state=completed_guidance_state_strategy())
@settings(max_examples=50)
def test_summary_mastery_updates_is_dict(state: GuidanceState):
    """
    Property 13: For any completed GuidanceState,
    mastery_updates should be a dict with float values in [0.0, 1.0].

    **Validates: Requirements 9.1, 9.2, 9.3**
    """
    kp_ids = [step.knowledge_point_id for step in state.steps]

    analysis = AnalysisResult(
        problem_text="测试题目",
        knowledge_points=kp_ids,
        difficulty_estimate=3,
        solution_steps=[f"step_{i}" for i in range(len(kp_ids))],
    )
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = asyncio.get_event_loop().run_until_complete(
        summarizer.summarize(state, analysis, profile, stream)
    )

    assert isinstance(summary.mastery_updates, dict)
    for kp_id, score in summary.mastery_updates.items():
        assert isinstance(kp_id, str)
        assert 0.0 <= score <= 1.0, f"Mastery score {score} out of range for {kp_id}"


@given(state=completed_guidance_state_strategy())
@settings(max_examples=50)
def test_summary_steps_needing_help_reflects_non_independent(state: GuidanceState):
    """
    Property 13: steps_needing_help should contain exactly those step indices
    that are NOT in state.independent_steps.

    **Validates: Requirements 9.1, 9.2, 9.3**
    """
    kp_ids = [step.knowledge_point_id for step in state.steps]

    analysis = AnalysisResult(
        problem_text="测试题目",
        knowledge_points=kp_ids,
        difficulty_estimate=3,
        solution_steps=[f"step_{i}" for i in range(len(kp_ids))],
    )
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = asyncio.get_event_loop().run_until_complete(
        summarizer.summarize(state, analysis, profile, stream)
    )

    expected_needing_help = [
        i for i in range(state.total_steps) if i not in state.independent_steps
    ]
    assert summary.steps_needing_help == expected_needing_help, (
        f"Expected steps_needing_help={expected_needing_help}, "
        f"got {summary.steps_needing_help}"
    )
