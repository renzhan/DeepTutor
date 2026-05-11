"""
Unit tests for SolveSummarizer:
- Summary contains all required fields after completing a problem
- steps_needing_help correctly reflects non-independent steps
- mastery_updates are computed for each knowledge point
- StreamBus result event is emitted

Requirements: 9.1, 9.2, 9.3
"""

import pytest

from deeptutor.core.stream_bus import StreamBus
from deeptutor.k12.agents.problem_analyzer import AnalysisResult
from deeptutor.k12.agents.socratic_guide import GuidanceState, GuidanceStep
from deeptutor.k12.agents.solve_summarizer import SolveSummarizer, SolveSummary
from deeptutor.k12.models import MasteryRecord, StudentProfileData
from deeptutor.k12.student_profile import StudentProfileService


# --- Helpers ---


def _make_profile(kp_ids: list[str], initial_score: float = 0.3) -> StudentProfileData:
    """Create a StudentProfileData with mastery records for given kp_ids."""
    mastery = {}
    for kp_id in kp_ids:
        mastery[kp_id] = MasteryRecord(
            knowledge_point_id=kp_id,
            score=initial_score,
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


def _make_state(
    num_steps: int = 3,
    independent_steps: list[int] | None = None,
) -> GuidanceState:
    """Create a completed GuidanceState with given number of steps."""
    if independent_steps is None:
        independent_steps = []

    kp_ids = [f"kp_{i}" for i in range(num_steps)]
    steps = [
        GuidanceStep(
            step_index=i,
            question=f"问题{i + 1}",
            hint=f"提示{i + 1}",
            expected_direction=f"方向{i + 1}",
            knowledge_point_id=kp_ids[i],
        )
        for i in range(num_steps)
    ]

    return GuidanceState(
        current_step=num_steps,
        total_steps=num_steps,
        completed_steps=list(range(num_steps)),
        error_count={},
        steps=steps,
        independent_steps=independent_steps,
    )


def _make_analysis(kp_ids: list[str]) -> AnalysisResult:
    """Create an AnalysisResult with given knowledge point IDs."""
    return AnalysisResult(
        problem_text="求解方程 2x + 3 = 7",
        knowledge_points=kp_ids,
        difficulty_estimate=2,
        solution_steps=[f"步骤{i + 1}" for i in range(len(kp_ids))],
    )


# --- Tests ---


@pytest.mark.asyncio
async def test_summary_contains_all_required_fields():
    """
    After completing a problem, the summary should contain all required fields:
    response, knowledge_points, mastery_updates, steps_needing_help, common_mistakes.
    Requirements: 9.1, 9.2
    """
    state = _make_state(num_steps=3, independent_steps=[0, 2])
    kp_ids = [step.knowledge_point_id for step in state.steps]
    analysis = _make_analysis(kp_ids)
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = await summarizer.summarize(state, analysis, profile, stream)

    # All fields should be present and non-empty/non-None
    assert isinstance(summary, SolveSummary)
    assert summary.response  # non-empty string
    assert len(summary.knowledge_points) == 3
    assert isinstance(summary.mastery_updates, dict)
    assert isinstance(summary.steps_needing_help, list)
    assert isinstance(summary.common_mistakes, list)
    assert len(summary.common_mistakes) > 0


@pytest.mark.asyncio
async def test_steps_needing_help_reflects_non_independent_steps():
    """
    steps_needing_help should contain exactly the step indices that are
    NOT in state.independent_steps.
    Requirements: 9.2
    """
    # Steps 0 and 2 are independent, step 1 needs help
    state = _make_state(num_steps=3, independent_steps=[0, 2])
    kp_ids = [step.knowledge_point_id for step in state.steps]
    analysis = _make_analysis(kp_ids)
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = await summarizer.summarize(state, analysis, profile, stream)

    assert summary.steps_needing_help == [1]


@pytest.mark.asyncio
async def test_steps_needing_help_all_independent():
    """
    When all steps are independent, steps_needing_help should be empty.
    Requirements: 9.2
    """
    state = _make_state(num_steps=3, independent_steps=[0, 1, 2])
    kp_ids = [step.knowledge_point_id for step in state.steps]
    analysis = _make_analysis(kp_ids)
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = await summarizer.summarize(state, analysis, profile, stream)

    assert summary.steps_needing_help == []


@pytest.mark.asyncio
async def test_steps_needing_help_none_independent():
    """
    When no steps are independent, all steps should need help.
    Requirements: 9.2
    """
    state = _make_state(num_steps=3, independent_steps=[])
    kp_ids = [step.knowledge_point_id for step in state.steps]
    analysis = _make_analysis(kp_ids)
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = await summarizer.summarize(state, analysis, profile, stream)

    assert summary.steps_needing_help == [0, 1, 2]


@pytest.mark.asyncio
async def test_mastery_updates_computed_for_each_knowledge_point():
    """
    mastery_updates should contain an entry for each knowledge point
    from the steps, with updated scores.
    Requirements: 9.3, 9.4
    """
    state = _make_state(num_steps=3, independent_steps=[0])
    kp_ids = [step.knowledge_point_id for step in state.steps]
    analysis = _make_analysis(kp_ids)
    profile = _make_profile(kp_ids, initial_score=0.3)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = await summarizer.summarize(state, analysis, profile, stream)

    # Each step's knowledge point should have a mastery update
    for step in state.steps:
        assert step.knowledge_point_id in summary.mastery_updates

    # Step 0 is independent: 0.3 + 0.15 = 0.45
    assert abs(summary.mastery_updates["kp_0"] - 0.45) < 1e-9

    # Steps 1, 2 are guided: 0.3 + 0.08 = 0.38
    assert abs(summary.mastery_updates["kp_1"] - 0.38) < 1e-9
    assert abs(summary.mastery_updates["kp_2"] - 0.38) < 1e-9


@pytest.mark.asyncio
async def test_mastery_updates_clamp_to_bounds():
    """
    Mastery updates should be clamped to [0.0, 1.0].
    Requirements: 9.4
    """
    state = _make_state(num_steps=1, independent_steps=[0])
    kp_ids = [step.knowledge_point_id for step in state.steps]
    analysis = _make_analysis(kp_ids)
    # Start with high mastery so INDEPENDENT (+0.15) would exceed 1.0
    profile = _make_profile(kp_ids, initial_score=0.95)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = await summarizer.summarize(state, analysis, profile, stream)

    # Should be clamped to 1.0
    assert summary.mastery_updates["kp_0"] == 1.0


@pytest.mark.asyncio
async def test_stream_bus_result_event_emitted():
    """
    The summarizer should emit a result event via StreamBus with
    response, knowledge_points, and mastery_updates.
    Requirements: 9.3
    """
    state = _make_state(num_steps=2, independent_steps=[0, 1])
    kp_ids = [step.knowledge_point_id for step in state.steps]
    analysis = _make_analysis(kp_ids)
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = await summarizer.summarize(state, analysis, profile, stream)

    # Check that a RESULT event was emitted
    result_events = [
        e for e in stream._history if e.type.value == "result"
    ]
    assert len(result_events) == 1

    event = result_events[0]
    assert event.source == "solve_summarizer"
    # The result metadata should contain response, knowledge_points, mastery_updates
    assert "response" in event.metadata
    assert "knowledge_points" in event.metadata
    assert "mastery_updates" in event.metadata


@pytest.mark.asyncio
async def test_summary_response_mentions_solving_path():
    """
    The summary response text should mention the solving path.
    Requirements: 9.1
    """
    state = _make_state(num_steps=2, independent_steps=[0])
    kp_ids = [step.knowledge_point_id for step in state.steps]
    analysis = _make_analysis(kp_ids)
    profile = _make_profile(kp_ids)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    summary = await summarizer.summarize(state, analysis, profile, stream)

    # Response should mention steps and their status
    assert "独立完成" in summary.response
    assert "需要引导" in summary.response


@pytest.mark.asyncio
async def test_profile_mastery_updated_after_summarize():
    """
    After summarize(), the profile's mastery records should be updated.
    Requirements: 9.4
    """
    state = _make_state(num_steps=2, independent_steps=[0])
    kp_ids = [step.knowledge_point_id for step in state.steps]
    analysis = _make_analysis(kp_ids)
    profile = _make_profile(kp_ids, initial_score=0.3)
    profile_service = StudentProfileService(storage_dir=None)
    summarizer = SolveSummarizer(profile_service)
    stream = StreamBus()

    await summarizer.summarize(state, analysis, profile, stream)

    # Profile should have been mutated
    assert abs(profile.mastery["kp_0"].score - 0.45) < 1e-9  # INDEPENDENT: +0.15
    assert abs(profile.mastery["kp_1"].score - 0.38) < 1e-9  # GUIDED: +0.08
