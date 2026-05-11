"""
End-to-end integration tests for the guided solve flow.
=========================================================

Tests the complete multi-turn solving session using actual components
(KnowledgeGraph, ProblemAnalyzer, SocraticGuide, AnswerValidator, SolveSummarizer).

Requirements: 1.3, 2.3, 8.2
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.capabilities.guided_solve import GuidedSolveCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _run_turn(context: UnifiedContext) -> tuple[list[StreamEvent], UnifiedContext]:
    """Run one turn of the capability and return collected events + updated context."""
    capability = GuidedSolveCapability()
    stream = StreamBus()

    events: list[StreamEvent] = []

    async def _collect():
        async for event in stream.subscribe():
            events.append(event)

    collect_task = asyncio.ensure_future(_collect())
    await capability.run(context, stream)
    await stream.close()
    await collect_task

    return events, context


# ─────────────────────────────────────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCompleteFlow:
    """Test complete solving flow: analyze → guide → validate → summarize."""

    @pytest.mark.asyncio
    async def test_full_multi_turn_session(self, monkeypatch, tmp_path):
        """
        Test a complete multi-turn solving session.
        Turn 1: Submit problem → get analysis + first guidance question
        Turn 2: Submit correct answer → advance to next step or complete
        """
        # Ensure KnowledgeGraph loads from the real data directory
        monkeypatch.chdir(tmp_path)
        # Copy data dir to tmp_path so the capability can find it
        data_src = Path(__file__).resolve().parents[2] / "deeptutor" / "k12" / "data"
        data_dst = tmp_path / "deeptutor" / "k12" / "data"
        data_dst.mkdir(parents=True)
        for f in data_src.glob("*.json"):
            (data_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        # Turn 1: Submit problem
        ctx = UnifiedContext(
            user_message="求解方程 2x + 3 = 7",
            session_id="integration_test_full",
        )
        events, ctx = await _run_turn(ctx)

        # Should have STAGE_START for analyzing and DONE
        stage_starts = [e for e in events if e.type == StreamEventType.STAGE_START]
        assert any(e.stage == "analyzing" for e in stage_starts)
        assert events[-1].type == StreamEventType.DONE

        # Session state should be saved in metadata
        assert "solving_session_state" in ctx.metadata
        state = ctx.metadata["solving_session_state"]
        assert state["total_steps"] > 0
        assert state["current_step"] == 0
        assert state["is_complete"] is False
        assert state["is_abandoned"] is False

        # Should have content events (first guidance question)
        content_events = [e for e in events if e.type == StreamEventType.CONTENT]
        assert len(content_events) >= 1

        # Turn 2: Submit answer matching expected direction
        expected_dir = state["steps"][0]["expected_direction"]
        ctx2 = UnifiedContext(
            user_message=expected_dir,
            session_id="integration_test_full",
            metadata={"solving_session_state": state},
        )
        events2, ctx2 = await _run_turn(ctx2)

        # Should have validating and guiding stages
        stage_starts2 = [e for e in events2 if e.type == StreamEventType.STAGE_START]
        assert any(e.stage == "validating" for e in stage_starts2)
        assert any(e.stage == "guiding" for e in stage_starts2)
        assert events2[-1].type == StreamEventType.DONE

        # State should have advanced
        state2 = ctx2.metadata["solving_session_state"]
        assert state2["current_step"] >= 1 or state2["is_complete"]

    @pytest.mark.asyncio
    async def test_wrong_answer_then_correct(self, monkeypatch, tmp_path):
        """Test submitting wrong answer then correct answer."""
        monkeypatch.chdir(tmp_path)
        data_src = Path(__file__).resolve().parents[2] / "deeptutor" / "k12" / "data"
        data_dst = tmp_path / "deeptutor" / "k12" / "data"
        data_dst.mkdir(parents=True)
        for f in data_src.glob("*.json"):
            (data_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        # Turn 1: Submit problem
        ctx = UnifiedContext(
            user_message="计算 3 + 5",
            session_id="integration_test_wrong",
        )
        events, ctx = await _run_turn(ctx)
        state = ctx.metadata["solving_session_state"]
        assert state["total_steps"] > 0

        # Turn 2: Submit wrong answer
        ctx2 = UnifiedContext(
            user_message="completely wrong answer xyz",
            session_id="integration_test_wrong",
            metadata={"solving_session_state": state},
        )
        events2, ctx2 = await _run_turn(ctx2)
        state2 = ctx2.metadata["solving_session_state"]

        # Should still be on same step (wrong answer doesn't advance)
        assert state2["current_step"] == 0
        # Error count should have increased
        assert any(v > 0 for v in state2["error_count"].values())

        # Turn 3: Submit correct answer (matching expected direction)
        expected_dir = state2["steps"][0]["expected_direction"]
        ctx3 = UnifiedContext(
            user_message=expected_dir,
            session_id="integration_test_wrong",
            metadata={"solving_session_state": state2},
        )
        events3, ctx3 = await _run_turn(ctx3)
        state3 = ctx3.metadata["solving_session_state"]

        # Should have advanced past step 0
        assert state3["current_step"] >= 1 or state3["is_complete"]

    @pytest.mark.asyncio
    async def test_abandon_mid_session(self, monkeypatch, tmp_path):
        """Test abandoning a problem mid-session."""
        monkeypatch.chdir(tmp_path)
        data_src = Path(__file__).resolve().parents[2] / "deeptutor" / "k12" / "data"
        data_dst = tmp_path / "deeptutor" / "k12" / "data"
        data_dst.mkdir(parents=True)
        for f in data_src.glob("*.json"):
            (data_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        # Turn 1: Submit problem
        ctx = UnifiedContext(
            user_message="求解方程 x + 1 = 5",
            session_id="integration_test_abandon",
        )
        events, ctx = await _run_turn(ctx)
        state = ctx.metadata["solving_session_state"]

        # Turn 2: Abandon
        ctx2 = UnifiedContext(
            user_message="放弃这道题",
            session_id="integration_test_abandon",
            metadata={"solving_session_state": state},
        )
        events2, ctx2 = await _run_turn(ctx2)

        # Should have DONE event
        assert events2[-1].type == StreamEventType.DONE

        # Should have abandon content message
        content_events = [e for e in events2 if e.type == StreamEventType.CONTENT]
        assert len(content_events) >= 1
        assert any("跳过" in e.content or "放弃" in e.content or "继续" in e.content for e in content_events)

        # State should be marked abandoned
        state2 = ctx2.metadata["solving_session_state"]
        assert state2["is_abandoned"] is True


class TestRAGIntegration:
    """Test RAG retrieval integration within the analysis stage."""

    @pytest.mark.asyncio
    async def test_rag_context_included_in_analysis(self, monkeypatch, tmp_path):
        """Test that RAG context is retrieved during analysis when kb_name is provided."""
        monkeypatch.chdir(tmp_path)
        data_src = Path(__file__).resolve().parents[2] / "deeptutor" / "k12" / "data"
        data_dst = tmp_path / "deeptutor" / "k12" / "data"
        data_dst.mkdir(parents=True)
        for f in data_src.glob("*.json"):
            (data_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        # Submit problem with a knowledge base specified
        ctx = UnifiedContext(
            user_message="有理数加减法：计算 (-3) + 5",
            session_id="integration_test_rag",
            knowledge_bases=["grade7_math"],
        )
        events, ctx = await _run_turn(ctx)

        # Analysis should complete successfully
        assert events[-1].type == StreamEventType.DONE
        assert "solving_session_state" in ctx.metadata

        # Progress events should mention knowledge point identification
        progress_events = [e for e in events if e.type == StreamEventType.PROGRESS]
        assert len(progress_events) >= 1

    @pytest.mark.asyncio
    async def test_analysis_works_without_rag(self, monkeypatch, tmp_path):
        """Test that analysis works even without a knowledge base (RAG unavailable)."""
        monkeypatch.chdir(tmp_path)
        data_src = Path(__file__).resolve().parents[2] / "deeptutor" / "k12" / "data"
        data_dst = tmp_path / "deeptutor" / "k12" / "data"
        data_dst.mkdir(parents=True)
        for f in data_src.glob("*.json"):
            (data_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        # Submit problem without knowledge base
        ctx = UnifiedContext(
            user_message="求解方程 x - 2 = 3",
            session_id="integration_test_no_rag",
        )
        events, ctx = await _run_turn(ctx)

        # Should still complete successfully
        assert events[-1].type == StreamEventType.DONE
        assert "solving_session_state" in ctx.metadata
        state = ctx.metadata["solving_session_state"]
        assert state["total_steps"] > 0


class TestMultiTurnStateRestore:
    """Test multi-turn conversation state restoration."""

    @pytest.mark.asyncio
    async def test_state_persists_across_turns(self, monkeypatch, tmp_path):
        """Test that session state is correctly persisted and restored across turns."""
        monkeypatch.chdir(tmp_path)
        data_src = Path(__file__).resolve().parents[2] / "deeptutor" / "k12" / "data"
        data_dst = tmp_path / "deeptutor" / "k12" / "data"
        data_dst.mkdir(parents=True)
        for f in data_src.glob("*.json"):
            (data_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        # Turn 1: Submit problem
        ctx = UnifiedContext(
            user_message="计算绝对值 |-5|",
            session_id="integration_test_state",
        )
        events, ctx = await _run_turn(ctx)
        state = ctx.metadata["solving_session_state"]

        # Verify state structure
        assert "problem_text" in state
        assert state["problem_text"] == "计算绝对值 |-5|"
        assert "steps" in state
        assert "current_step" in state
        assert "total_steps" in state
        assert "guidance_level" in state
        assert "error_count" in state
        assert "completed_steps" in state
        assert "independent_steps" in state

        # Turn 2: Simulate state restoration by passing state in metadata
        ctx2 = UnifiedContext(
            user_message="some answer",
            session_id="integration_test_state",
            metadata={"solving_session_state": state},
        )
        events2, ctx2 = await _run_turn(ctx2)

        # Should have processed the answer (validating + guiding stages)
        stage_starts = [e for e in events2 if e.type == StreamEventType.STAGE_START]
        assert any(e.stage == "validating" for e in stage_starts)
        assert events2[-1].type == StreamEventType.DONE

    @pytest.mark.asyncio
    async def test_complete_all_steps_triggers_summary(self, monkeypatch, tmp_path):
        """Test that completing all steps triggers the summarizing stage."""
        monkeypatch.chdir(tmp_path)
        data_src = Path(__file__).resolve().parents[2] / "deeptutor" / "k12" / "data"
        data_dst = tmp_path / "deeptutor" / "k12" / "data"
        data_dst.mkdir(parents=True)
        for f in data_src.glob("*.json"):
            (data_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        # Turn 1: Submit problem
        ctx = UnifiedContext(
            user_message="有理数的概念",
            session_id="integration_test_summary",
        )
        events, ctx = await _run_turn(ctx)
        state = ctx.metadata["solving_session_state"]

        # Iterate through all steps by submitting correct answers
        for step_idx in range(state["total_steps"]):
            expected_dir = state["steps"][step_idx]["expected_direction"]
            ctx_next = UnifiedContext(
                user_message=expected_dir,
                session_id="integration_test_summary",
                metadata={"solving_session_state": state},
            )
            events_next, ctx_next = await _run_turn(ctx_next)
            state = ctx_next.metadata["solving_session_state"]

            if state["is_complete"]:
                # Should have summarizing stage
                stage_starts = [
                    e for e in events_next if e.type == StreamEventType.STAGE_START
                ]
                assert any(e.stage == "summarizing" for e in stage_starts)
                # Should have a RESULT event from summarizer
                result_events = [
                    e for e in events_next if e.type == StreamEventType.RESULT
                ]
                assert len(result_events) >= 1
                break

        # Verify session is marked complete
        assert state["is_complete"] is True


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_empty_data_dir_uses_empty_graph(self, monkeypatch, tmp_path):
        """Test that missing data directory results in empty graph (graceful degradation)."""
        monkeypatch.chdir(tmp_path)
        # Create empty data dir (no JSON files)
        data_dst = tmp_path / "deeptutor" / "k12" / "data"
        data_dst.mkdir(parents=True)

        ctx = UnifiedContext(
            user_message="求解方程 x = 5",
            session_id="integration_test_empty_graph",
        )
        events, ctx = await _run_turn(ctx)

        # Should still complete (with 0 steps since no knowledge points)
        assert events[-1].type == StreamEventType.DONE
        state = ctx.metadata["solving_session_state"]
        # With empty graph, no knowledge points are identified, so 0 steps
        assert state["total_steps"] == 0

    @pytest.mark.asyncio
    async def test_nonexistent_data_dir_graceful(self, monkeypatch, tmp_path):
        """Test that nonexistent data directory is handled gracefully."""
        monkeypatch.chdir(tmp_path)
        # Don't create data dir at all

        ctx = UnifiedContext(
            user_message="求解方程 x = 5",
            session_id="integration_test_no_dir",
        )
        events, ctx = await _run_turn(ctx)

        # Should still complete without crashing
        assert events[-1].type == StreamEventType.DONE

    @pytest.mark.asyncio
    async def test_event_sequence_correctness(self, monkeypatch, tmp_path):
        """Test that events follow the correct sequence: STAGE_START → content → STAGE_END → DONE."""
        monkeypatch.chdir(tmp_path)
        data_src = Path(__file__).resolve().parents[2] / "deeptutor" / "k12" / "data"
        data_dst = tmp_path / "deeptutor" / "k12" / "data"
        data_dst.mkdir(parents=True)
        for f in data_src.glob("*.json"):
            (data_dst / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        ctx = UnifiedContext(
            user_message="有理数加减法",
            session_id="integration_test_events",
        )
        events, ctx = await _run_turn(ctx)

        # DONE must be last
        assert events[-1].type == StreamEventType.DONE

        # Every STAGE_START must have a matching STAGE_END
        starts = [
            (i, e.stage) for i, e in enumerate(events)
            if e.type == StreamEventType.STAGE_START
        ]
        ends = [
            (i, e.stage) for i, e in enumerate(events)
            if e.type == StreamEventType.STAGE_END
        ]
        start_stages = [s[1] for s in starts]
        end_stages = [s[1] for s in ends]
        for stage_name in start_stages:
            assert stage_name in end_stages, f"STAGE_START '{stage_name}' has no matching STAGE_END"

        # STAGE_END must come after its STAGE_START
        for stage_name in start_stages:
            start_idx = next(i for i, s in starts if s == stage_name)
            end_idx = next(i for i, s in ends if s == stage_name)
            assert end_idx > start_idx
