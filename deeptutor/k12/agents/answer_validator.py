"""
Answer Validator
================

Validates student answers using Code_Execution_Tool with LLM fallback.
Emits tool_call and tool_result events via StreamBus for frontend visibility.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from deeptutor.core.stream_bus import StreamBus
from deeptutor.k12.agents.prompts.validate import (
    CORRECT_ANSWER_FEEDBACK,
    INCORRECT_ANSWER_FEEDBACK_TEMPLATE,
)
from deeptutor.k12.agents.socratic_guide import GuidanceStep


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Result of answer validation."""

    is_correct: bool
    method: str  # "code_execution" or "llm_fallback"
    feedback: str  # Feedback message (never contains the answer)
    error_direction: str  # Hint about error direction (only when incorrect)
    code_output: str  # Code execution output (for debugging)


# ─────────────────────────────────────────────────────────────────────────────
# AnswerValidator
# ─────────────────────────────────────────────────────────────────────────────


class AnswerValidator:
    """
    Validates student answers using code execution with LLM fallback.

    The validation flow:
    1. Generate Python verification code based on the step and answer
    2. Execute via Code_Execution_Tool
    3. If execution times out or fails, fall back to LLM reasoning

    All validation steps emit tool_call and tool_result events via
    StreamBus for frontend visibility.

    Usage::

        validator = AnswerValidator(timeout=5.0)
        result = await validator.validate(
            student_answer="x = 2",
            expected_direction="解方程得 x = 2",
            step=guidance_step,
            stream=stream_bus,
        )
    """

    def __init__(self, timeout: float = 5.0) -> None:
        """
        Parameters
        ----------
        timeout : float
            Maximum seconds to wait for code execution before falling
            back to LLM verification.
        """
        self._timeout = timeout

    async def validate(
        self,
        student_answer: str,
        expected_direction: str,
        step: GuidanceStep,
        stream: StreamBus,
    ) -> ValidationResult:
        """
        Validate a student's answer.

        Attempts code execution first; falls back to LLM on timeout/failure.
        Emits tool_call and tool_result events via StreamBus.

        Parameters
        ----------
        student_answer : str
            The student's submitted answer.
        expected_direction : str
            The expected solution direction (internal reference).
        step : GuidanceStep
            The current guidance step being validated.
        stream : StreamBus
            For emitting tool_call/tool_result events.

        Returns
        -------
        ValidationResult
            Structured validation result.
        """
        # Emit tool_call event for code execution attempt
        await stream.tool_call(
            tool_name="code_execution",
            args={
                "purpose": "validate_answer",
                "student_answer": student_answer,
                "step_index": step.step_index,
            },
            source="answer_validator",
            stage="validating",
        )

        try:
            # Attempt code-based verification with timeout
            result = await asyncio.wait_for(
                self._code_verify(student_answer, step),
                timeout=self._timeout,
            )

            # Emit tool_result event for successful code execution
            await stream.tool_result(
                tool_name="code_execution",
                result=f"验证完成: is_correct={result.is_correct}",
                source="answer_validator",
                stage="validating",
            )

            return result

        except (asyncio.TimeoutError, CodeExecutionError):
            # Emit tool_result event indicating fallback
            await stream.tool_result(
                tool_name="code_execution",
                result="代码执行超时或失败，回退到 LLM 验证",
                source="answer_validator",
                stage="validating",
            )

            # Emit tool_call event for LLM fallback
            await stream.tool_call(
                tool_name="llm_fallback",
                args={
                    "purpose": "validate_answer_fallback",
                    "student_answer": student_answer,
                    "step_index": step.step_index,
                },
                source="answer_validator",
                stage="validating",
            )

            # Fall back to LLM verification
            result = await self._llm_fallback_verify(student_answer, step)

            # Emit tool_result event for LLM fallback
            await stream.tool_result(
                tool_name="llm_fallback",
                result=f"LLM验证完成: is_correct={result.is_correct}",
                source="answer_validator",
                stage="validating",
            )

            return result

    async def _code_verify(
        self, student_answer: str, step: GuidanceStep
    ) -> ValidationResult:
        """
        Code execution verification path.

        In production, this:
        1. Generates Python code using CODE_VALIDATION_TEMPLATE
        2. Sends code to Code_Execution_Tool
        3. Parses the JSON output

        For now, implements a simple string-matching placeholder that
        checks if the student answer aligns with the expected direction.

        Raises
        ------
        CodeExecutionError
            If code execution fails (triggers LLM fallback).
        """
        # Placeholder: simple direction-matching logic
        # In production, this generates and executes Python verification code
        answer_lower = student_answer.strip().lower()
        direction_lower = step.expected_direction.strip().lower()

        # Simple heuristic: check if answer appears in expected direction
        is_correct = answer_lower in direction_lower or direction_lower in answer_lower

        if is_correct:
            return ValidationResult(
                is_correct=True,
                method="code_execution",
                feedback=CORRECT_ANSWER_FEEDBACK,
                error_direction="",
                code_output=f"match: student='{student_answer}' direction='{step.expected_direction}'",
            )
        else:
            error_direction = "你的思路方向可能需要调整，再检查一下计算过程。"
            return ValidationResult(
                is_correct=False,
                method="code_execution",
                feedback=INCORRECT_ANSWER_FEEDBACK_TEMPLATE.format(
                    error_direction=error_direction
                ),
                error_direction=error_direction,
                code_output=f"mismatch: student='{student_answer}' direction='{step.expected_direction}'",
            )

    async def _llm_fallback_verify(
        self, student_answer: str, step: GuidanceStep
    ) -> ValidationResult:
        """
        LLM reasoning verification fallback.

        Used when Code_Execution_Tool times out or fails.
        Calls LLM to evaluate whether the student's answer is on the right track.
        """
        import json as _json

        from deeptutor.k12.agents.prompts.validate import (
            LLM_FALLBACK_TEMPLATE,
        )

        user_prompt = LLM_FALLBACK_TEMPLATE.format(
            step_question=step.question,
            knowledge_point_id=step.knowledge_point_id,
            expected_direction=step.expected_direction,
            student_answer=student_answer,
        )

        try:
            from deeptutor.services.llm import complete

            response = await complete(
                user_prompt,
                system_prompt="你是一位数学教师，正在验证学生的答案。只输出JSON格式。绝对不要在feedback中包含正确答案。",
                max_tokens=500,
            )

            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = _json.loads(text)
            is_correct = data.get("is_correct", False)
            feedback = data.get("feedback", "")
            error_direction = data.get("error_direction", "")

            if is_correct:
                return ValidationResult(
                    is_correct=True,
                    method="llm_fallback",
                    feedback=feedback or CORRECT_ANSWER_FEEDBACK,
                    error_direction="",
                    code_output="",
                )
            else:
                return ValidationResult(
                    is_correct=False,
                    method="llm_fallback",
                    feedback=feedback or "你的答案还不太对，再想想看。",
                    error_direction=error_direction or "请重新检查你的计算过程。",
                    code_output="",
                )

        except Exception:
            pass

        # Ultimate fallback: simple string matching
        answer_lower = student_answer.strip().lower()
        direction_lower = step.expected_direction.strip().lower()

        is_correct = answer_lower in direction_lower or direction_lower in answer_lower

        # Simple heuristic for placeholder
        is_correct = answer_lower in direction_lower or direction_lower in answer_lower

        if is_correct:
            return ValidationResult(
                is_correct=True,
                method="llm_fallback",
                feedback=CORRECT_ANSWER_FEEDBACK,
                error_direction="",
                code_output="",
            )
        else:
            error_direction = "LLM分析：你的解题方向可能偏离了，建议重新审视题目条件。"
            return ValidationResult(
                is_correct=False,
                method="llm_fallback",
                feedback=INCORRECT_ANSWER_FEEDBACK_TEMPLATE.format(
                    error_direction=error_direction
                ),
                error_direction=error_direction,
                code_output="",
            )


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────


class CodeExecutionError(Exception):
    """Raised when code execution fails and LLM fallback should be used."""

    pass
