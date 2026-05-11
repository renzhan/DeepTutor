"""
Socratic Guide Engine
=====================

Provides Socratic-method guided problem solving with adaptive
guidance levels based on student mastery.

The engine determines how much help a student needs based on their
mastery scores, generates step-by-step guidance questions, and
manages the interactive guidance session state.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from deeptutor.core.stream_bus import StreamBus
from deeptutor.k12.knowledge_graph import KnowledgeGraph
from deeptutor.k12.student_profile import StudentProfileService


# ─────────────────────────────────────────────────────────────────────────────
# Enums & Data Classes
# ─────────────────────────────────────────────────────────────────────────────


class GuidanceLevel(str, Enum):
    """Guidance intensity level."""

    FULL = "full"  # 完整引导：细粒度步骤 + 知识点提示
    MODERATE = "moderate"  # 适度引导：关键转折点提问
    MINIMAL = "minimal"  # 最少引导：仅在请求时提供方向


@dataclass
class GuidanceStep:
    """A single guidance step in the solving process."""

    step_index: int
    question: str  # 引导性问题
    hint: str  # 知识点提示
    expected_direction: str  # 期望的解答方向（内部使用）
    knowledge_point_id: str  # 关联知识点 ID


@dataclass
class GuidanceState:
    """Mutable state for a guidance session."""

    current_step: int = 0
    total_steps: int = 0
    completed_steps: list[int] = field(default_factory=list)
    error_count: dict[int, int] = field(default_factory=dict)  # step_index -> count
    guidance_level: GuidanceLevel = GuidanceLevel.FULL
    steps: list[GuidanceStep] = field(default_factory=list)
    independent_steps: list[int] = field(default_factory=list)  # 独立完成的步骤


# ─────────────────────────────────────────────────────────────────────────────
# SocraticGuide
# ─────────────────────────────────────────────────────────────────────────────


class SocraticGuide:
    """
    Socratic-method guidance engine.

    Determines guidance level from student mastery, generates step-by-step
    guidance questions, and manages the interactive Q&A loop with adaptive
    difficulty downgrade on repeated errors.

    Usage::

        guide = SocraticGuide(knowledge_graph, student_profile_service)
        level = guide.determine_guidance_level([0.3, 0.5, 0.2])
        steps = await guide.generate_steps(problem_text, kp_ids, level, stream)
        state = GuidanceState(total_steps=len(steps), steps=steps, guidance_level=level)
        state = await guide.provide_guidance(state, student_answer, is_correct, stream)
    """

    def __init__(
        self,
        knowledge_graph: KnowledgeGraph,
        student_profile_service: StudentProfileService,
    ) -> None:
        self._kg = knowledge_graph
        self._profile_service = student_profile_service

    # ─── Guidance Level Determination ────────────────────────────────────

    def determine_guidance_level(self, mastery_scores: list[float]) -> GuidanceLevel:
        """
        Determine guidance level from average mastery scores.

        Rules (Requirement 3.1):
        - avg < 0.4  → FULL
        - 0.4 <= avg <= 0.7 → MODERATE
        - avg > 0.7  → MINIMAL

        Empty scores default to FULL (most supportive).
        """
        if not mastery_scores:
            return GuidanceLevel.FULL

        avg = sum(mastery_scores) / len(mastery_scores)

        if avg < 0.4:
            return GuidanceLevel.FULL
        elif avg <= 0.7:
            return GuidanceLevel.MODERATE
        else:
            return GuidanceLevel.MINIMAL

    # ─── Step Generation ─────────────────────────────────────────────────

    async def generate_steps(
        self,
        problem_text: str,
        knowledge_point_ids: list[str],
        guidance_level: GuidanceLevel,
        stream: StreamBus,
    ) -> list[GuidanceStep]:
        """
        Generate guidance steps for a problem using LLM.

        Calls LLM to generate step-by-step guidance questions tailored
        to the specific problem and guidance level.

        Parameters
        ----------
        problem_text : str
            The math problem text.
        knowledge_point_ids : list[str]
            Ordered list of relevant knowledge point IDs.
        guidance_level : GuidanceLevel
            Determines step granularity.
        stream : StreamBus
            For emitting progress events.

        Returns
        -------
        list[GuidanceStep]
            Ordered guidance steps.
        """
        import json as _json

        from deeptutor.k12.agents.prompts.guide import GENERATE_STEPS_TEMPLATE

        # Build knowledge points description
        kp_descriptions = []
        for kp_id in knowledge_point_ids:
            point = self._kg.get_point(kp_id)
            name = point.name if point else kp_id
            kp_descriptions.append(f"- {kp_id}: {name}")
        kp_text = "\n".join(kp_descriptions) if kp_descriptions else "无"

        user_prompt = GENERATE_STEPS_TEMPLATE.format(
            problem_text=problem_text,
            knowledge_points=kp_text,
            guidance_level=guidance_level.value,
        )

        try:
            from deeptutor.services.llm import complete

            response = await complete(
                user_prompt,
                system_prompt="你是一位数学辅导老师，请生成解题引导步骤。只输出JSON数组格式。",
                max_tokens=2000,
            )

            # Parse JSON response
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            raw_steps = _json.loads(text)
            if isinstance(raw_steps, list):
                steps: list[GuidanceStep] = []
                for i, raw in enumerate(raw_steps):
                    step = GuidanceStep(
                        step_index=i,
                        question=raw.get("question", f"第{i+1}步，你打算怎么做？"),
                        hint=raw.get("hint", "想想相关的知识点。"),
                        expected_direction=raw.get("expected_direction", ""),
                        knowledge_point_id=raw.get("knowledge_point_id", knowledge_point_ids[i % len(knowledge_point_ids)] if knowledge_point_ids else ""),
                    )
                    steps.append(step)

                if steps:
                    await stream.progress(
                        message=f"已生成 {len(steps)} 个引导步骤（{guidance_level.value}级别）",
                        current=len(steps),
                        total=len(steps),
                        source="socratic_guide",
                        stage="guiding",
                    )
                    return steps

        except Exception:
            pass

        # Fallback: generate placeholder steps
        steps = []
        for i, kp_id in enumerate(knowledge_point_ids):
            point = self._kg.get_point(kp_id)
            name = point.name if point else kp_id

            if guidance_level == GuidanceLevel.FULL:
                step = GuidanceStep(
                    step_index=i,
                    question=f"让我们来看看这道题中与「{name}」相关的部分。你能想到应该怎么处理吗？",
                    hint=f"提示：回忆一下「{name}」的关键概念和公式。",
                    expected_direction=f"应用{name}的方法来解决这一步",
                    knowledge_point_id=kp_id,
                )
            elif guidance_level == GuidanceLevel.MODERATE:
                step = GuidanceStep(
                    step_index=i,
                    question=f"接下来这一步是关键转折点。关于「{name}」，你打算怎么做？",
                    hint=f"想想{name}的核心思路。",
                    expected_direction=f"应用{name}的方法",
                    knowledge_point_id=kp_id,
                )
            else:
                step = GuidanceStep(
                    step_index=i,
                    question=f"继续解题吧。如果需要帮助，可以告诉我。",
                    hint=f"方向：{name}",
                    expected_direction=f"独立应用{name}",
                    knowledge_point_id=kp_id,
                )
            steps.append(step)

        await stream.progress(
            message=f"已生成 {len(steps)} 个引导步骤（{guidance_level.value}级别）",
            current=len(steps),
            total=len(steps),
            source="socratic_guide",
            stage="guiding",
        )

        return steps

    # ─── Guidance Interaction ────────────────────────────────────────────

    async def provide_guidance(
        self,
        state: GuidanceState,
        student_answer: str,
        is_correct: bool,
        stream: StreamBus,
    ) -> GuidanceState:
        """
        Process a student answer and provide next guidance.

        Behavior (Requirements 3.5, 3.6, 3.7):
        - Correct answer → mark step as completed/independent, advance
        - Incorrect answer → increment error_count for current step
        - 3 consecutive errors on same step → downgrade guidance level

        The method never reveals the final answer directly.

        Parameters
        ----------
        state : GuidanceState
            Current session state (mutated in place and returned).
        student_answer : str
            The student's response text.
        is_correct : bool
            Whether the answer was validated as correct.
        stream : StreamBus
            For emitting guidance content to the frontend.

        Returns
        -------
        GuidanceState
            Updated state after processing.
        """
        current_idx = state.current_step

        if is_correct:
            # Mark step as completed and independent
            if current_idx not in state.completed_steps:
                state.completed_steps.append(current_idx)
            if current_idx not in state.independent_steps:
                state.independent_steps.append(current_idx)

            # Advance to next step
            state.current_step = current_idx + 1

            if state.current_step < state.total_steps:
                next_step = state.steps[state.current_step]
                await stream.content(
                    f"很好！你答对了。让我们继续下一步。\n\n{next_step.question}",
                    source="socratic_guide",
                    stage="guiding",
                )
            else:
                await stream.content(
                    "太棒了！你已经完成了所有步骤！",
                    source="socratic_guide",
                    stage="guiding",
                )
        else:
            # Increment error count for current step
            error_count = state.error_count.get(current_idx, 0) + 1
            state.error_count[current_idx] = error_count

            if error_count >= 3:
                # Downgrade guidance level after 3 consecutive errors
                state.guidance_level = self.downgrade_guidance(state, current_idx)
                current_step = state.steps[current_idx]

                # Remove from independent steps (student needed extra help)
                if current_idx in state.independent_steps:
                    state.independent_steps.remove(current_idx)

                await stream.content(
                    f"没关系，让我给你更多提示。\n\n{current_step.hint}",
                    source="socratic_guide",
                    stage="guiding",
                )
            else:
                current_step = state.steps[current_idx]
                await stream.content(
                    f"再想想看，换个角度试试。\n\n{current_step.question}",
                    source="socratic_guide",
                    stage="guiding",
                )

        return state

    # ─── Guidance Downgrade ──────────────────────────────────────────────

    def downgrade_guidance(self, state: GuidanceState, step_index: int) -> GuidanceLevel:
        """
        Downgrade guidance level when student has 3+ consecutive errors.

        Requirement 3.6: MINIMAL → MODERATE → FULL (cannot go below FULL).

        Parameters
        ----------
        state : GuidanceState
            Current state (used to read current guidance level).
        step_index : int
            The step where errors occurred (for logging/future use).

        Returns
        -------
        GuidanceLevel
            The new (lower) guidance level.
        """
        current_level = state.guidance_level

        if current_level == GuidanceLevel.MINIMAL:
            return GuidanceLevel.MODERATE
        elif current_level == GuidanceLevel.MODERATE:
            return GuidanceLevel.FULL
        # Already at FULL — stay at FULL
        return GuidanceLevel.FULL
