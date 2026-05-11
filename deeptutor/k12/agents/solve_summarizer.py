"""
Solve Summarizer
================

Generates solve summaries after a student completes all steps of a
guided problem-solving session. Reviews the solving path, marks steps
that needed help, computes mastery updates, and updates the student profile.

Requirements: 9.1, 9.2, 9.3, 9.4
"""

from __future__ import annotations

from dataclasses import dataclass, field

from deeptutor.core.stream_bus import StreamBus
from deeptutor.k12.agents.problem_analyzer import AnalysisResult
from deeptutor.k12.agents.prompts.summarize import SUMMARIZE_TEMPLATE
from deeptutor.k12.agents.socratic_guide import GuidanceState
from deeptutor.k12.models import CompletionType, StudentProfileData
from deeptutor.k12.student_profile import StudentProfileService


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SolveSummary:
    """Result of solve summarization."""

    response: str  # 总结文本
    knowledge_points: list[str] = field(default_factory=list)  # 涉及知识点 ID
    mastery_updates: dict[str, float] = field(default_factory=dict)  # 知识点 -> 新掌握度
    steps_needing_help: list[int] = field(default_factory=list)  # 需要引导的步骤索引
    common_mistakes: list[str] = field(default_factory=list)  # 易错点提醒


# ─────────────────────────────────────────────────────────────────────────────
# SolveSummarizer
# ─────────────────────────────────────────────────────────────────────────────


class SolveSummarizer:
    """
    Generates solve summaries after guided problem solving.

    Reviews the solving path, identifies steps where the student needed
    help, computes mastery score updates, persists them to the student
    profile, and emits a structured result event via StreamBus.

    Usage::

        summarizer = SolveSummarizer(student_profile_service)
        summary = await summarizer.summarize(state, analysis, profile, stream)
    """

    def __init__(self, student_profile_service: StudentProfileService) -> None:
        self._profile_service = student_profile_service

    async def summarize(
        self,
        state: GuidanceState,
        analysis: AnalysisResult,
        profile: StudentProfileData,
        stream: StreamBus,
    ) -> SolveSummary:
        """
        Generate solve summary.

        Steps:
        1. Review solving path
        2. Mark steps needing help (not in independent_steps)
        3. Compute mastery updates (INDEPENDENT for independent steps, GUIDED for others)
        4. Update StudentProfile
        5. Send result event via StreamBus

        Parameters
        ----------
        state : GuidanceState
            The completed guidance session state.
        analysis : AnalysisResult
            The original problem analysis result.
        profile : StudentProfileData
            The student's profile data (will be mutated with mastery updates).
        stream : StreamBus
            For emitting result events.

        Returns
        -------
        SolveSummary
            Structured summary of the solving session.
        """
        # Step 1 & 2: Determine which steps needed help
        steps_needing_help = [
            i for i in range(state.total_steps) if i not in state.independent_steps
        ]

        # Step 3: Compute mastery updates
        mastery_updates = self._compute_mastery_updates(state, profile)

        # Step 4: Collect common mistakes from analysis knowledge points
        common_mistakes = self._collect_common_mistakes(analysis)

        # Step 5: Generate summary text
        response = self._generate_summary_text(state, analysis, steps_needing_help)

        summary = SolveSummary(
            response=response,
            knowledge_points=analysis.knowledge_points,
            mastery_updates=mastery_updates,
            steps_needing_help=steps_needing_help,
            common_mistakes=common_mistakes,
        )

        # Step 6: Send result event via StreamBus
        await stream.result(
            data={
                "response": summary.response,
                "knowledge_points": summary.knowledge_points,
                "mastery_updates": summary.mastery_updates,
            },
            source="solve_summarizer",
        )

        return summary

    # ─── Private Helpers ─────────────────────────────────────────────────

    def _compute_mastery_updates(
        self,
        state: GuidanceState,
        profile: StudentProfileData,
    ) -> dict[str, float]:
        """
        Compute mastery score updates for each knowledge point.

        Independent steps get INDEPENDENT completion (+0.15),
        guided steps get GUIDED completion (+0.08).

        Returns a dict mapping knowledge_point_id -> new mastery score.
        """
        mastery_updates: dict[str, float] = {}

        for step in state.steps:
            kp_id = step.knowledge_point_id
            if step.step_index in state.independent_steps:
                completion = CompletionType.INDEPENDENT
            else:
                completion = CompletionType.GUIDED

            new_score = self._profile_service.update_mastery(
                profile, kp_id, completion
            )
            mastery_updates[kp_id] = new_score

        return mastery_updates

    def _collect_common_mistakes(self, analysis: AnalysisResult) -> list[str]:
        """
        Collect common mistake reminders for the knowledge points involved.

        In production, this would query the knowledge graph for detailed
        common mistakes. For now, generates placeholder reminders.
        """
        common_mistakes: list[str] = []
        for kp_id in analysis.knowledge_points:
            common_mistakes.append(f"注意{kp_id}相关的常见错误")
        return common_mistakes

    def _generate_summary_text(
        self,
        state: GuidanceState,
        analysis: AnalysisResult,
        steps_needing_help: list[int],
    ) -> str:
        """
        Generate human-readable summary text.

        In production, this would call an LLM with SUMMARIZE_TEMPLATE.
        For now, generates a structured placeholder summary.
        """
        # Build solving path description
        path_parts: list[str] = []
        for step in state.steps:
            if step.step_index in state.independent_steps:
                status = "独立完成"
            else:
                status = "需要引导"
            path_parts.append(
                f"步骤{step.step_index + 1}（{step.knowledge_point_id}）：{status}"
            )

        solving_path = "；".join(path_parts)

        # Build knowledge points list
        kp_list = "、".join(analysis.knowledge_points) if analysis.knowledge_points else "无"

        # Build help steps description
        if steps_needing_help:
            help_desc = "、".join(f"步骤{i + 1}" for i in steps_needing_help)
        else:
            help_desc = "无（全部独立完成）"

        # Compose summary
        summary_lines = [
            f"解题总结：",
            f"",
            f"解题路径：{solving_path}",
            f"",
            f"涉及知识点：{kp_list}",
            f"",
            f"需要复习的重点：{help_desc}",
            f"",
            f"继续加油！多练习薄弱环节，你会越来越熟练的。",
        ]

        return "\n".join(summary_lines)
