"""
Unit tests for ProblemAnalyzer and AnswerValidator:
- ProblemAnalyzer.order_by_prerequisites correctly orders knowledge points
- ProblemAnalyzer.analyze emits progress events via StreamBus
- AnswerValidator.validate returns correct ValidationResult structure
- AnswerValidator handles timeout/failure by falling back to LLM
- Correct answer produces is_correct=True with empty error_direction
- Incorrect answer produces is_correct=False with non-empty error_direction (no answer revealed)

Requirements: 2.1, 2.2, 4.1, 4.4
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from deeptutor.core.context import Attachment
from deeptutor.core.stream_bus import StreamBus
from deeptutor.k12.agents.answer_validator import (
    AnswerValidator,
    CodeExecutionError,
    ValidationResult,
)
from deeptutor.k12.agents.problem_analyzer import AnalysisResult, ProblemAnalyzer
from deeptutor.k12.agents.socratic_guide import GuidanceStep
from deeptutor.k12.knowledge_graph import KnowledgeGraph, KnowledgePointNode


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_knowledge_graph() -> KnowledgeGraph:
    """Create a test knowledge graph with dependency chain: A → B → C."""
    kg = KnowledgeGraph()
    # C has no prerequisites
    kg._nodes["kp_c"] = KnowledgePointNode(
        id="kp_c",
        name="基础运算",
        grade="7",
        semester="1",
        chapter="1",
        difficulty=1,
    )
    kg._edges["kp_c"] = []

    # B depends on C
    kg._nodes["kp_b"] = KnowledgePointNode(
        id="kp_b",
        name="一元一次方程",
        grade="7",
        semester="1",
        chapter="2",
        difficulty=2,
    )
    kg._edges["kp_b"] = ["kp_c"]

    # A depends on B
    kg._nodes["kp_a"] = KnowledgePointNode(
        id="kp_a",
        name="方程应用题",
        grade="7",
        semester="1",
        chapter="3",
        difficulty=3,
    )
    kg._edges["kp_a"] = ["kp_b"]

    return kg


def _make_guidance_step(
    expected_direction: str = "x = 2",
) -> GuidanceStep:
    """Create a test guidance step."""
    return GuidanceStep(
        step_index=0,
        question="请解方程 2x + 3 = 7",
        hint="移项后合并同类项",
        expected_direction=expected_direction,
        knowledge_point_id="kp_b",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ProblemAnalyzer Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestProblemAnalyzerOrderByPrerequisites:
    """Tests for ProblemAnalyzer.order_by_prerequisites."""

    def test_orders_by_dependency(self):
        """
        Knowledge points should be ordered so prerequisites come first.
        Requirements: 2.4
        """
        kg = _make_knowledge_graph()
        analyzer = ProblemAnalyzer(kg)

        # Input in reverse dependency order
        result = analyzer.order_by_prerequisites(["kp_a", "kp_b", "kp_c"])

        # C should come before B, B before A (topological order)
        assert result.index("kp_c") < result.index("kp_b")
        assert result.index("kp_b") < result.index("kp_a")

    def test_unknown_points_appended_at_end(self):
        """
        Points not in the graph should be appended at the end.
        """
        kg = _make_knowledge_graph()
        analyzer = ProblemAnalyzer(kg)

        result = analyzer.order_by_prerequisites(["kp_b", "unknown_kp", "kp_c"])

        # Known points are sorted (kp_c before kp_b), unknown appended at end
        known_part = [kp for kp in result if kp != "unknown_kp"]
        assert known_part.index("kp_c") < known_part.index("kp_b")
        assert result[-1] == "unknown_kp"

    def test_empty_list_returns_empty(self):
        """Empty input returns empty output."""
        kg = _make_knowledge_graph()
        analyzer = ProblemAnalyzer(kg)

        result = analyzer.order_by_prerequisites([])
        assert result == []

    def test_single_point_returns_same(self):
        """Single point returns the same list."""
        kg = _make_knowledge_graph()
        analyzer = ProblemAnalyzer(kg)

        result = analyzer.order_by_prerequisites(["kp_b"])
        assert result == ["kp_b"]


class TestProblemAnalyzerAnalyze:
    """Tests for ProblemAnalyzer.analyze with StreamBus events."""

    @pytest.mark.asyncio
    async def test_analyze_emits_progress_events(self):
        """
        analyze() should emit progress events via StreamBus.
        Requirements: 2.5
        """
        kg = _make_knowledge_graph()
        analyzer = ProblemAnalyzer(kg)
        stream = StreamBus()

        result = await analyzer.analyze(
            problem_text="求解方程 2x + 3 = 7",
            attachments=[],
            kb_name="grade7_math",
            stream=stream,
        )

        # Check progress events were emitted
        progress_events = [
            e for e in stream._history if e.type.value == "progress"
        ]
        assert len(progress_events) >= 4  # At least 4 progress updates

        # Verify final progress message mentions completion
        last_progress = progress_events[-1]
        assert "分析完成" in last_progress.content

    @pytest.mark.asyncio
    async def test_analyze_returns_valid_result(self):
        """
        analyze() should return a properly structured AnalysisResult.
        Requirements: 2.1
        """
        kg = _make_knowledge_graph()
        analyzer = ProblemAnalyzer(kg)
        stream = StreamBus()

        result = await analyzer.analyze(
            problem_text="求解方程 2x + 3 = 7",
            attachments=[],
            kb_name=None,
            stream=stream,
        )

        assert isinstance(result, AnalysisResult)
        assert result.problem_text == "求解方程 2x + 3 = 7"
        assert isinstance(result.knowledge_points, list)
        assert 1 <= result.difficulty_estimate <= 5
        assert isinstance(result.solution_steps, list)
        assert result.has_image is False

    @pytest.mark.asyncio
    async def test_analyze_with_image_attachment(self):
        """
        analyze() should detect image attachments and set has_image=True.
        Requirements: 2.2
        """
        kg = _make_knowledge_graph()
        analyzer = ProblemAnalyzer(kg)
        stream = StreamBus()

        attachments = [
            Attachment(type="image", url="https://example.com/math.png", filename="math.png")
        ]

        result = await analyzer.analyze(
            problem_text="如图所示，求三角形面积",
            attachments=attachments,
            kb_name="grade7_math",
            stream=stream,
        )

        assert result.has_image is True

    @pytest.mark.asyncio
    async def test_analyze_with_rag_retrieval(self):
        """
        analyze() should include RAG context when kb_name is provided.
        Requirements: 2.3
        """
        kg = _make_knowledge_graph()
        analyzer = ProblemAnalyzer(kg)
        stream = StreamBus()

        result = await analyzer.analyze(
            problem_text="求解方程 2x + 3 = 7",
            attachments=[],
            kb_name="grade7_math",
            stream=stream,
        )

        assert result.rag_context != ""
        assert "grade7_math" in result.rag_context


# ─────────────────────────────────────────────────────────────────────────────
# AnswerValidator Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAnswerValidatorStructure:
    """Tests for AnswerValidator.validate result structure."""

    @pytest.mark.asyncio
    async def test_validate_returns_validation_result(self):
        """
        validate() should return a properly structured ValidationResult.
        Requirements: 4.1
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        result = await validator.validate(
            student_answer="x = 2",
            expected_direction="x = 2",
            step=step,
            stream=stream,
        )

        assert isinstance(result, ValidationResult)
        assert isinstance(result.is_correct, bool)
        assert result.method in ("code_execution", "llm_fallback")
        assert isinstance(result.feedback, str)
        assert isinstance(result.error_direction, str)
        assert isinstance(result.code_output, str)

    @pytest.mark.asyncio
    async def test_validate_emits_tool_events(self):
        """
        validate() should emit tool_call and tool_result events via StreamBus.
        Requirements: 4.5
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        await validator.validate(
            student_answer="x = 2",
            expected_direction="x = 2",
            step=step,
            stream=stream,
        )

        tool_call_events = [
            e for e in stream._history if e.type.value == "tool_call"
        ]
        tool_result_events = [
            e for e in stream._history if e.type.value == "tool_result"
        ]

        assert len(tool_call_events) >= 1
        assert len(tool_result_events) >= 1
        assert tool_call_events[0].content == "code_execution"


class TestAnswerValidatorCorrectAnswer:
    """Tests for correct answer validation."""

    @pytest.mark.asyncio
    async def test_correct_answer_is_correct_true(self):
        """
        A correct answer should produce is_correct=True.
        Requirements: 4.2
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        result = await validator.validate(
            student_answer="x = 2",
            expected_direction="x = 2",
            step=step,
            stream=stream,
        )

        assert result.is_correct is True

    @pytest.mark.asyncio
    async def test_correct_answer_empty_error_direction(self):
        """
        A correct answer should have empty error_direction.
        Requirements: 4.2
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        result = await validator.validate(
            student_answer="x = 2",
            expected_direction="x = 2",
            step=step,
            stream=stream,
        )

        assert result.error_direction == ""

    @pytest.mark.asyncio
    async def test_correct_answer_has_positive_feedback(self):
        """
        A correct answer should have encouraging feedback.
        Requirements: 4.2
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        result = await validator.validate(
            student_answer="x = 2",
            expected_direction="x = 2",
            step=step,
            stream=stream,
        )

        assert result.feedback != ""
        assert "正确" in result.feedback


class TestAnswerValidatorIncorrectAnswer:
    """Tests for incorrect answer validation."""

    @pytest.mark.asyncio
    async def test_incorrect_answer_is_correct_false(self):
        """
        An incorrect answer should produce is_correct=False.
        Requirements: 4.3
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        result = await validator.validate(
            student_answer="x = 5",
            expected_direction="x = 2",
            step=step,
            stream=stream,
        )

        assert result.is_correct is False

    @pytest.mark.asyncio
    async def test_incorrect_answer_has_error_direction(self):
        """
        An incorrect answer should have non-empty error_direction.
        Requirements: 4.3
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        result = await validator.validate(
            student_answer="x = 5",
            expected_direction="x = 2",
            step=step,
            stream=stream,
        )

        assert result.error_direction != ""

    @pytest.mark.asyncio
    async def test_incorrect_answer_feedback_does_not_reveal_answer(self):
        """
        Feedback for incorrect answer must NOT contain the correct answer.
        Requirements: 4.3
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        result = await validator.validate(
            student_answer="x = 5",
            expected_direction="x = 2",
            step=step,
            stream=stream,
        )

        # The feedback should not reveal "x = 2" (the correct answer)
        assert "x = 2" not in result.feedback
        assert "2" not in result.error_direction or "方向" in result.error_direction


class TestAnswerValidatorFallback:
    """Tests for timeout/failure fallback to LLM."""

    @pytest.mark.asyncio
    async def test_timeout_falls_back_to_llm(self):
        """
        When code execution times out, validator should fall back to LLM.
        Requirements: 4.4
        """
        validator = AnswerValidator(timeout=0.01)  # Very short timeout
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        # Patch _code_verify to simulate a timeout (sleep longer than timeout)
        async def slow_verify(student_answer, step):
            await asyncio.sleep(1.0)  # Much longer than 0.01s timeout
            return ValidationResult(
                is_correct=True,
                method="code_execution",
                feedback="",
                error_direction="",
                code_output="",
            )

        with patch.object(validator, "_code_verify", side_effect=slow_verify):
            result = await validator.validate(
                student_answer="x = 2",
                expected_direction="x = 2",
                step=step,
                stream=stream,
            )

        assert result.method == "llm_fallback"

    @pytest.mark.asyncio
    async def test_code_execution_error_falls_back_to_llm(self):
        """
        When code execution raises CodeExecutionError, validator should fall back to LLM.
        Requirements: 4.4
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        # Patch _code_verify to raise CodeExecutionError
        with patch.object(
            validator,
            "_code_verify",
            side_effect=CodeExecutionError("execution failed"),
        ):
            result = await validator.validate(
                student_answer="x = 2",
                expected_direction="x = 2",
                step=step,
                stream=stream,
            )

        assert result.method == "llm_fallback"

    @pytest.mark.asyncio
    async def test_fallback_emits_both_tool_events(self):
        """
        When falling back to LLM, both code_execution and llm_fallback
        tool events should be emitted.
        Requirements: 4.4, 4.5
        """
        validator = AnswerValidator(timeout=5.0)
        stream = StreamBus()
        step = _make_guidance_step(expected_direction="x = 2")

        with patch.object(
            validator,
            "_code_verify",
            side_effect=CodeExecutionError("execution failed"),
        ):
            await validator.validate(
                student_answer="x = 2",
                expected_direction="x = 2",
                step=step,
                stream=stream,
            )

        tool_call_events = [
            e for e in stream._history if e.type.value == "tool_call"
        ]

        # Should have both code_execution and llm_fallback tool_call events
        tool_names = [e.content for e in tool_call_events]
        assert "code_execution" in tool_names
        assert "llm_fallback" in tool_names
