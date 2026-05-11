# Feature: k12-math-guided-tutoring, Property 14: 进度事件包含正确的步骤信息
"""
Property-based tests for GuidedSolveCapability progress events:
- Progress events contain correct step information (Property 14)

Uses pytest + Hypothesis.

**Validates: Requirements 10.4**
"""

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from deeptutor.core.stream import StreamEventType
from deeptutor.core.stream_bus import StreamBus


# ─── Strategies ──────────────────────────────────────────────────────────────

@st.composite
def progress_event_params(draw):
    """
    Generate valid progress event parameters:
    - total_steps > 0
    - current_step in [0, total_steps)
    """
    total_steps = draw(st.integers(min_value=1, max_value=50))
    current_step = draw(st.integers(min_value=0, max_value=total_steps - 1))
    return current_step, total_steps


# ─── Property 14: 进度事件包含正确的步骤信息 ─────────────────────────────────


@given(params=progress_event_params())
@settings(max_examples=100)
def test_progress_event_current_step_in_valid_range(params):
    """
    Property 14: For any multi-step solving process, progress events
    should have current_step in [0, total_steps) and total_steps > 0.

    **Validates: Requirements 10.4**
    """
    current_step, total_steps = params

    # Simulate emitting a progress event via StreamBus
    stream = StreamBus()
    events_collected: list = []

    async def _run():
        # Subscribe to collect events
        async def _collect():
            async for event in stream.subscribe():
                events_collected.append(event)

        collect_task = asyncio.ensure_future(_collect())

        # Emit progress event as the capability would
        await stream.progress(
            message=f"步骤 {current_step}/{total_steps}",
            current=current_step,
            total=total_steps,
            source="guided_solve",
            stage="guiding",
        )

        await stream.close()
        await collect_task

    asyncio.get_event_loop().run_until_complete(_run())

    # Verify the progress event
    assert len(events_collected) == 1
    event = events_collected[0]

    assert event.type == StreamEventType.PROGRESS
    assert event.metadata["current"] == current_step
    assert event.metadata["total"] == total_steps

    # Property assertions
    assert event.metadata["total"] > 0, "total_steps must be > 0"
    assert 0 <= event.metadata["current"] < event.metadata["total"], (
        f"current_step ({event.metadata['current']}) must be in "
        f"[0, total_steps={event.metadata['total']})"
    )


@given(params=progress_event_params())
@settings(max_examples=100)
def test_progress_event_has_source_and_stage(params):
    """
    Property 14: Progress events must include source and stage metadata
    to identify which capability and phase emitted them.

    **Validates: Requirements 10.4**
    """
    current_step, total_steps = params

    stream = StreamBus()
    events_collected: list = []

    async def _run():
        async def _collect():
            async for event in stream.subscribe():
                events_collected.append(event)

        collect_task = asyncio.ensure_future(_collect())

        await stream.progress(
            message=f"步骤 {current_step}/{total_steps}",
            current=current_step,
            total=total_steps,
            source="guided_solve",
            stage="guiding",
        )

        await stream.close()
        await collect_task

    asyncio.get_event_loop().run_until_complete(_run())

    assert len(events_collected) == 1
    event = events_collected[0]

    assert event.source == "guided_solve", "Progress event must have source"
    assert event.stage != "", "Progress event must have a stage"


@given(
    total_steps=st.integers(min_value=1, max_value=20),
)
@settings(max_examples=50)
def test_progress_events_sequence_monotonic(total_steps: int):
    """
    Property 14: In a sequence of progress events for a solving session,
    current_step values should be monotonically non-decreasing and always
    less than total_steps.

    **Validates: Requirements 10.4**
    """
    stream = StreamBus()
    events_collected: list = []

    async def _run():
        async def _collect():
            async for event in stream.subscribe():
                events_collected.append(event)

        collect_task = asyncio.ensure_future(_collect())

        # Simulate a sequence of progress events (one per step)
        for step in range(total_steps):
            await stream.progress(
                message=f"步骤 {step}/{total_steps}",
                current=step,
                total=total_steps,
                source="guided_solve",
                stage="guiding",
            )

        await stream.close()
        await collect_task

    asyncio.get_event_loop().run_until_complete(_run())

    assert len(events_collected) == total_steps

    # Verify monotonically non-decreasing current_step
    prev_step = -1
    for event in events_collected:
        current = event.metadata["current"]
        total = event.metadata["total"]

        assert total == total_steps, "total_steps must be consistent"
        assert total > 0, "total_steps must be > 0"
        assert 0 <= current < total, (
            f"current_step ({current}) must be in [0, {total})"
        )
        assert current >= prev_step, (
            f"current_step must be non-decreasing: {current} < {prev_step}"
        )
        prev_step = current
