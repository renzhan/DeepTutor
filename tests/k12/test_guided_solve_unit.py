"""
Unit tests for GuidedSolveCapability.

Tests:
- ChatOrchestrator routes active_capability="guided_solve" to GuidedSolveCapability
- StreamBus event sequence (STAGE_START/END, content, progress, DONE)
- Multi-turn conversation state restoration
- Abandon problem flow

Requirements: 1.2, 1.3, 8.2, 8.4, 10.1, 10.5
"""

import asyncio

import pytest

from deeptutor.capabilities.guided_solve import GuidedSolveCapability
from deeptutor.core.capability_protocol import CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _collect_events(stream: StreamBus) -> list[StreamEvent]:
    """Collect all events from a stream bus."""
    events: list[StreamEvent] = []
    async for event in stream.subscribe():
        events.append(event)
    return events


def _run_capability(context: UnifiedContext) -> list[StreamEvent]:
    """Run the GuidedSolveCapability and return collected events."""
    capability = GuidedSolveCapability()
    stream = StreamBus()

    async def _execute():
        collect_task = asyncio.ensure_future(_collect_events(stream))
        await capability.run(context, stream)
        await stream.close()
        return await collect_task

    return asyncio.get_event_loop().run_until_complete(_execute())


# ─── Test: Capability Manifest ───────────────────────────────────────────────


class TestCapabilityManifest:
    """Test GuidedSolveCapability manifest configuration."""

    def test_manifest_name(self):
        """Capability name should be 'guided_solve'."""
        cap = GuidedSolveCapability()
        assert cap.manifest.name == "guided_solve"
        assert cap.name == "guided_solve"

    def test_manifest_stages(self):
        """Capability should define four stages."""
        cap = GuidedSolveCapability()
        assert cap.manifest.stages == [
            "analyzing", "guiding", "validating", "summarizing"
        ]

    def test_manifest_tools_used(self):
        """Capability should declare rag and code_execution tools."""
        cap = GuidedSolveCapability()
        assert cap.manifest.tools_used == ["rag", "code_execution"]

    def test_manifest_cli_aliases(self):
        """Capability should have guided_solve and tutor as CLI aliases."""
        cap = GuidedSolveCapability()
        assert "guided_solve" in cap.manifest.cli_aliases
        assert "tutor" in cap.manifest.cli_aliases

    def test_manifest_is_capability_manifest(self):
        """Manifest should be a CapabilityManifest instance."""
        cap = GuidedSolveCapability()
        assert isinstance(cap.manifest, CapabilityManifest)


# ─── Test: Registration ──────────────────────────────────────────────────────


class TestRegistration:
    """Test that guided_solve is registered in builtin capabilities."""

    def test_registered_in_builtin_capabilities(self):
        """guided_solve should be in BUILTIN_CAPABILITY_CLASSES."""
        from deeptutor.runtime.bootstrap.builtin_capabilities import (
            BUILTIN_CAPABILITY_CLASSES,
        )

        assert "guided_solve" in BUILTIN_CAPABILITY_CLASSES
        assert (
            BUILTIN_CAPABILITY_CLASSES["guided_solve"]
            == "deeptutor.capabilities.guided_solve:GuidedSolveCapability"
        )

    def test_capability_can_be_imported(self):
        """The registered class path should be importable."""
        import importlib

        module_path, class_name = (
            "deeptutor.capabilities.guided_solve:GuidedSolveCapability"
        ).rsplit(":", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        assert cls is GuidedSolveCapability


# ─── Test: StreamBus Event Sequence ──────────────────────────────────────────


class TestStreamBusEventSequence:
    """Test that the capability emits correct event sequences."""

    def test_new_problem_emits_stage_start_end_and_done(self):
        """New problem should emit STAGE_START, STAGE_END for analyzing, and DONE."""
        context = UnifiedContext(
            user_message="求解方程 2x + 3 = 7",
            session_id="test_session",
        )

        events = _run_capability(context)

        # Should have at least STAGE_START, STAGE_END, and DONE
        event_types = [e.type for e in events]
        assert StreamEventType.STAGE_START in event_types
        assert StreamEventType.STAGE_END in event_types
        assert StreamEventType.DONE in event_types

    def test_done_event_is_last(self):
        """DONE event should be the last event emitted."""
        context = UnifiedContext(
            user_message="求解方程 2x + 3 = 7",
            session_id="test_session",
        )

        events = _run_capability(context)

        # DONE should be the last event
        assert events[-1].type == StreamEventType.DONE
        assert events[-1].source == "guided_solve"

    def test_analyzing_stage_events(self):
        """Analyzing stage should emit STAGE_START and STAGE_END with correct name."""
        context = UnifiedContext(
            user_message="求解方程 2x + 3 = 7",
            session_id="test_session",
        )

        events = _run_capability(context)

        # Find analyzing stage events
        stage_starts = [
            e for e in events
            if e.type == StreamEventType.STAGE_START and e.stage == "analyzing"
        ]
        stage_ends = [
            e for e in events
            if e.type == StreamEventType.STAGE_END and e.stage == "analyzing"
        ]

        assert len(stage_starts) >= 1, "Should have at least one analyzing STAGE_START"
        assert len(stage_ends) >= 1, "Should have at least one analyzing STAGE_END"

    def test_progress_events_emitted(self):
        """Progress events should be emitted during the solving process."""
        context = UnifiedContext(
            user_message="求解方程 2x + 3 = 7",
            session_id="test_session",
        )

        events = _run_capability(context)

        progress_events = [e for e in events if e.type == StreamEventType.PROGRESS]
        assert len(progress_events) > 0, "Should emit at least one progress event"

    def test_content_events_emitted(self):
        """Content events should be emitted (guidance questions)."""
        context = UnifiedContext(
            user_message="求解方程 2x + 3 = 7",
            session_id="test_session",
        )

        events = _run_capability(context)

        content_events = [e for e in events if e.type == StreamEventType.CONTENT]
        assert len(content_events) > 0, "Should emit at least one content event"


# ─── Test: Multi-turn Conversation State Restoration ─────────────────────────


class TestMultiTurnStateRestoration:
    """Test session state persistence and restoration across turns."""

    def test_session_state_saved_to_metadata(self):
        """After first turn, session state should be saved in metadata."""
        context = UnifiedContext(
            user_message="求解方程 2x + 3 = 7",
            session_id="test_session",
        )

        capability = GuidedSolveCapability()
        stream = StreamBus()

        async def _execute():
            collect_task = asyncio.ensure_future(_collect_events(stream))
            await capability.run(context, stream)
            await stream.close()
            await collect_task

        asyncio.get_event_loop().run_until_complete(_execute())

        # Session state should be saved
        assert "solving_session_state" in context.metadata
        state = context.metadata["solving_session_state"]
        assert state["problem_text"] == "求解方程 2x + 3 = 7"
        assert state["total_steps"] > 0
        assert state["current_step"] == 0

    def test_session_state_restored_on_second_turn(self):
        """Second turn should restore session state and continue from where left off."""
        # First turn: set up session state
        first_context = UnifiedContext(
            user_message="求解方程 2x + 3 = 7",
            session_id="test_session",
        )

        capability = GuidedSolveCapability()
        stream1 = StreamBus()

        async def _first_turn():
            collect_task = asyncio.ensure_future(_collect_events(stream1))
            await capability.run(first_context, stream1)
            await stream1.close()
            await collect_task

        asyncio.get_event_loop().run_until_complete(_first_turn())

        # Second turn: restore state and provide an answer
        session_state = first_context.metadata["solving_session_state"]
        second_context = UnifiedContext(
            user_message="x = 2",
            session_id="test_session",
            metadata={"solving_session_state": session_state},
        )

        stream2 = StreamBus()

        async def _second_turn():
            collect_task = asyncio.ensure_future(_collect_events(stream2))
            await capability.run(second_context, stream2)
            await stream2.close()
            return await collect_task

        events = asyncio.get_event_loop().run_until_complete(_second_turn())

        # Should have validating and guiding stages
        event_types = [e.type for e in events]
        assert StreamEventType.STAGE_START in event_types
        assert StreamEventType.DONE in event_types

        # Session state should be updated
        updated_state = second_context.metadata["solving_session_state"]
        assert updated_state is not None

    def test_state_includes_step_progress(self):
        """Session state should track step progress across turns."""
        # Set up a session state with known values
        session_state = {
            "problem_text": "求解 x + 1 = 3",
            "analysis_result": {"knowledge_points": ["kp1"], "difficulty": 2},
            "current_step": 0,
            "total_steps": 1,
            "completed_steps": [],
            "error_count": {},
            "guidance_level": "full",
            "steps": [
                {
                    "question": "这道题需要什么操作？",
                    "hint": "移项",
                    "expected_direction": "x = 2",
                    "knowledge_point_id": "kp1",
                }
            ],
            "independent_steps": [],
            "is_complete": False,
            "is_abandoned": False,
        }

        # Provide the correct answer
        context = UnifiedContext(
            user_message="x = 2",
            session_id="test_session",
            metadata={"solving_session_state": session_state},
        )

        events = _run_capability(context)

        # Should have completed the step
        updated_state = context.metadata["solving_session_state"]
        assert updated_state["current_step"] >= 1 or updated_state["is_complete"]


# ─── Test: Abandon Problem Flow ──────────────────────────────────────────────


class TestAbandonFlow:
    """Test the abandon/skip problem flow."""

    def test_abandon_with_chinese_keyword(self):
        """Abandon keyword '放弃' should trigger abandon flow."""
        context = UnifiedContext(
            user_message="我想放弃这道题",
            session_id="test_session",
        )

        events = _run_capability(context)

        # Should emit content (abandon message) and DONE
        content_events = [e for e in events if e.type == StreamEventType.CONTENT]
        assert len(content_events) >= 1
        assert "跳过" in content_events[0].content or "放弃" in content_events[0].content or "下次" in content_events[0].content

        # Should emit DONE
        assert events[-1].type == StreamEventType.DONE

    def test_abandon_with_english_keyword(self):
        """Abandon keyword 'skip' should trigger abandon flow."""
        context = UnifiedContext(
            user_message="I want to skip this problem",
            session_id="test_session",
        )

        events = _run_capability(context)

        # Should emit DONE
        assert events[-1].type == StreamEventType.DONE

    def test_abandon_with_existing_session_marks_abandoned(self):
        """Abandoning with existing session state should mark is_abandoned=True."""
        session_state = {
            "problem_text": "求解 x + 1 = 3",
            "analysis_result": {"knowledge_points": ["kp1"], "difficulty": 2},
            "current_step": 0,
            "total_steps": 2,
            "completed_steps": [],
            "error_count": {},
            "guidance_level": "full",
            "steps": [
                {
                    "question": "q1",
                    "hint": "h1",
                    "expected_direction": "d1",
                    "knowledge_point_id": "kp1",
                },
                {
                    "question": "q2",
                    "hint": "h2",
                    "expected_direction": "d2",
                    "knowledge_point_id": "kp2",
                },
            ],
            "independent_steps": [],
            "is_complete": False,
            "is_abandoned": False,
        }

        context = UnifiedContext(
            user_message="放弃",
            session_id="test_session",
            metadata={"solving_session_state": session_state},
        )

        events = _run_capability(context)

        # Session state should be marked as abandoned
        updated_state = context.metadata["solving_session_state"]
        assert updated_state["is_abandoned"] is True

    def test_abandon_without_session_state(self):
        """Abandoning without existing session should still emit DONE gracefully."""
        context = UnifiedContext(
            user_message="quit",
            session_id="test_session",
        )

        events = _run_capability(context)

        # Should still emit DONE without error
        assert events[-1].type == StreamEventType.DONE

    def test_abandon_emits_content_message(self):
        """Abandon flow should emit a friendly content message."""
        context = UnifiedContext(
            user_message="不做了",
            session_id="test_session",
        )

        events = _run_capability(context)

        content_events = [e for e in events if e.type == StreamEventType.CONTENT]
        assert len(content_events) >= 1
        # The message should be encouraging
        assert any("下次" in e.content or "继续" in e.content for e in content_events)
