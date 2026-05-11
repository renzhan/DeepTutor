"""
Unit tests for SocraticGuide:
- FULL level produces detailed steps with knowledge point hints
- MODERATE level produces key turning point questions
- MINIMAL level produces minimal direction
- Correct answer advances step
- Incorrect answer increments error_count
- 3 consecutive errors trigger downgrade

Requirements: 3.1, 3.2, 3.3, 3.4, 3.6
"""

import pytest

from deeptutor.core.stream_bus import StreamBus
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


def _make_state(level: GuidanceLevel) -> GuidanceState:
    """Create a GuidanceState with 2 steps at the given level."""
    return GuidanceState(
        current_step=0,
        total_steps=2,
        guidance_level=level,
        steps=[
            GuidanceStep(
                step_index=0,
                question="问题1",
                hint="提示1",
                expected_direction="方向1",
                knowledge_point_id="kp_a",
            ),
            GuidanceStep(
                step_index=1,
                question="问题2",
                hint="提示2",
                expected_direction="方向2",
                knowledge_point_id="kp_b",
            ),
        ],
    )


# --- Tests for generate_steps with different guidance levels ---


@pytest.mark.asyncio
async def test_full_level_generates_detailed_steps():
    """
    FULL level should produce steps with detailed questions and knowledge point hints.
    Requirements: 3.2
    """
    guide = _make_guide()
    stream = StreamBus()

    steps = await guide.generate_steps(
        problem_text="求解方程 2x + 3 = 7",
        knowledge_point_ids=["kp_a", "kp_b"],
        guidance_level=GuidanceLevel.FULL,
        stream=stream,
    )

    assert len(steps) == 2

    # FULL level: each step has a detailed question mentioning the knowledge point
    for step in steps:
        assert step.question  # non-empty question
        assert step.hint  # non-empty hint
        assert "知识点" in step.question or step.knowledge_point_id in step.question
        # Hint should reference the knowledge point concept
        assert "提示" in step.hint or "回忆" in step.hint


@pytest.mark.asyncio
async def test_moderate_level_generates_turning_point_questions():
    """
    MODERATE level should produce key turning point questions only.
    Requirements: 3.3
    """
    guide = _make_guide()
    stream = StreamBus()

    steps = await guide.generate_steps(
        problem_text="求解方程 2x + 3 = 7",
        knowledge_point_ids=["kp_a", "kp_b"],
        guidance_level=GuidanceLevel.MODERATE,
        stream=stream,
    )

    assert len(steps) == 2

    # MODERATE level: questions focus on key turning points
    for step in steps:
        assert step.question  # non-empty question
        assert "关键转折点" in step.question or "打算怎么做" in step.question
        # Hint is shorter/more concise than FULL
        assert step.hint
        assert "核心思路" in step.hint or step.knowledge_point_id in step.hint


@pytest.mark.asyncio
async def test_minimal_level_generates_minimal_direction():
    """
    MINIMAL level should produce minimal direction, only when asked.
    Requirements: 3.4
    """
    guide = _make_guide()
    stream = StreamBus()

    steps = await guide.generate_steps(
        problem_text="求解方程 2x + 3 = 7",
        knowledge_point_ids=["kp_a", "kp_b"],
        guidance_level=GuidanceLevel.MINIMAL,
        stream=stream,
    )

    assert len(steps) == 2

    # MINIMAL level: generic encouragement, direction only in hint
    for step in steps:
        assert step.question  # non-empty
        assert "继续" in step.question or "帮助" in step.question
        # Hint provides direction but is minimal
        assert step.hint
        assert "方向" in step.hint


# --- Tests for provide_guidance ---


@pytest.mark.asyncio
async def test_correct_answer_advances_step():
    """
    A correct answer should mark the step as completed and advance to the next step.
    Requirements: 3.5
    """
    guide = _make_guide()
    stream = StreamBus()
    state = _make_state(GuidanceLevel.FULL)

    updated_state = await guide.provide_guidance(
        state=state,
        student_answer="x = 2",
        is_correct=True,
        stream=stream,
    )

    assert updated_state.current_step == 1
    assert 0 in updated_state.completed_steps
    assert 0 in updated_state.independent_steps

    # Check that a content event was emitted with encouragement
    content_events = [
        e for e in stream._history if e.type.value == "content"
    ]
    assert len(content_events) >= 1
    assert "答对" in content_events[0].content or "继续" in content_events[0].content


@pytest.mark.asyncio
async def test_incorrect_answer_increments_error_count():
    """
    An incorrect answer should increment error_count for the current step.
    Requirements: 3.6
    """
    guide = _make_guide()
    stream = StreamBus()
    state = _make_state(GuidanceLevel.FULL)

    updated_state = await guide.provide_guidance(
        state=state,
        student_answer="x = 5",
        is_correct=False,
        stream=stream,
    )

    assert updated_state.error_count.get(0) == 1
    assert updated_state.current_step == 0  # stays on same step

    # Check that a content event was emitted with encouragement to retry
    content_events = [
        e for e in stream._history if e.type.value == "content"
    ]
    assert len(content_events) >= 1
    assert "再想想" in content_events[0].content or "换个角度" in content_events[0].content


@pytest.mark.asyncio
async def test_three_consecutive_errors_triggers_downgrade():
    """
    3 consecutive errors on the same step should trigger guidance level downgrade.
    Requirements: 3.6
    """
    guide = _make_guide()
    stream = StreamBus()
    state = _make_state(GuidanceLevel.MODERATE)

    # Simulate 2 prior errors
    state.error_count[0] = 2

    # Third error triggers downgrade
    updated_state = await guide.provide_guidance(
        state=state,
        student_answer="wrong answer",
        is_correct=False,
        stream=stream,
    )

    assert updated_state.error_count[0] == 3
    assert updated_state.guidance_level == GuidanceLevel.FULL  # MODERATE → FULL

    # Check that a hint was provided
    content_events = [
        e for e in stream._history if e.type.value == "content"
    ]
    assert len(content_events) >= 1
    assert "提示" in content_events[0].content or "更多" in content_events[0].content


@pytest.mark.asyncio
async def test_three_errors_on_full_stays_full():
    """
    3 consecutive errors at FULL level should stay at FULL (cannot go lower).
    Requirements: 3.6
    """
    guide = _make_guide()
    stream = StreamBus()
    state = _make_state(GuidanceLevel.FULL)

    # Simulate 2 prior errors
    state.error_count[0] = 2

    updated_state = await guide.provide_guidance(
        state=state,
        student_answer="wrong answer",
        is_correct=False,
        stream=stream,
    )

    assert updated_state.error_count[0] == 3
    assert updated_state.guidance_level == GuidanceLevel.FULL  # stays FULL


@pytest.mark.asyncio
async def test_three_errors_on_minimal_downgrades_to_moderate():
    """
    3 consecutive errors at MINIMAL level should downgrade to MODERATE.
    Requirements: 3.6
    """
    guide = _make_guide()
    stream = StreamBus()
    state = _make_state(GuidanceLevel.MINIMAL)

    # Simulate 2 prior errors
    state.error_count[0] = 2

    updated_state = await guide.provide_guidance(
        state=state,
        student_answer="wrong answer",
        is_correct=False,
        stream=stream,
    )

    assert updated_state.error_count[0] == 3
    assert updated_state.guidance_level == GuidanceLevel.MODERATE  # MINIMAL → MODERATE


# --- Tests for determine_guidance_level ---


def test_empty_scores_default_to_full():
    """Empty mastery scores should default to FULL (most supportive)."""
    guide = _make_guide()
    level = guide.determine_guidance_level([])
    assert level == GuidanceLevel.FULL


def test_low_mastery_returns_full():
    """Mastery < 0.4 should return FULL. Requirements: 3.1"""
    guide = _make_guide()
    assert guide.determine_guidance_level([0.1, 0.2, 0.3]) == GuidanceLevel.FULL


def test_medium_mastery_returns_moderate():
    """Mastery in [0.4, 0.7] should return MODERATE. Requirements: 3.1"""
    guide = _make_guide()
    assert guide.determine_guidance_level([0.5, 0.6]) == GuidanceLevel.MODERATE


def test_high_mastery_returns_minimal():
    """Mastery > 0.7 should return MINIMAL. Requirements: 3.1"""
    guide = _make_guide()
    assert guide.determine_guidance_level([0.8, 0.9]) == GuidanceLevel.MINIMAL


@pytest.mark.asyncio
async def test_complete_all_steps_emits_completion_message():
    """
    Completing the last step should emit a completion message.
    Requirements: 3.5
    """
    guide = _make_guide()
    stream = StreamBus()
    state = _make_state(GuidanceLevel.FULL)
    state.current_step = 1  # on last step

    updated_state = await guide.provide_guidance(
        state=state,
        student_answer="correct",
        is_correct=True,
        stream=stream,
    )

    assert updated_state.current_step == 2  # past total_steps
    assert 1 in updated_state.completed_steps

    content_events = [
        e for e in stream._history if e.type.value == "content"
    ]
    assert len(content_events) >= 1
    assert "完成" in content_events[0].content or "棒" in content_events[0].content
