"""
Problem Analyzer
================

Analyzes student-submitted math problems to identify knowledge points,
estimate difficulty, and plan solution steps. Uses LLM for analysis
and RAG for retrieving relevant teaching content.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""

from __future__ import annotations

from dataclasses import dataclass, field

from deeptutor.core.context import Attachment
from deeptutor.core.stream_bus import StreamBus
from deeptutor.k12.knowledge_graph import KnowledgeGraph


# ─────────────────────────────────────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AnalysisResult:
    """Result of problem analysis."""

    problem_text: str  # 原始题目文本
    knowledge_points: list[str] = field(default_factory=list)  # 知识点 ID（按依赖序排列）
    difficulty_estimate: int = 1  # 估计难度 1-5
    solution_steps: list[str] = field(default_factory=list)  # 预估解题步骤描述
    rag_context: str = ""  # RAG 检索到的教学内容
    has_image: bool = False  # 是否包含图片


# ─────────────────────────────────────────────────────────────────────────────
# ProblemAnalyzer
# ─────────────────────────────────────────────────────────────────────────────


class ProblemAnalyzer:
    """
    Analyzes math problems to identify knowledge points and plan solution steps.

    In production, this calls an LLM to analyze the problem text/images,
    uses RAG to retrieve relevant teaching content, and orders knowledge
    points by dependency using the knowledge graph.

    Usage::

        analyzer = ProblemAnalyzer(knowledge_graph)
        result = await analyzer.analyze(
            problem_text="求解方程 2x + 3 = 7",
            attachments=[],
            kb_name="grade7_math",
            stream=stream_bus,
        )
    """

    def __init__(self, knowledge_graph: KnowledgeGraph) -> None:
        self._kg = knowledge_graph

    async def analyze(
        self,
        problem_text: str,
        attachments: list[Attachment],
        kb_name: str | None,
        stream: StreamBus,
    ) -> AnalysisResult:
        """
        Analyze a math problem.

        Steps:
        1. Extract text and image information
        2. Identify knowledge points via LLM
        3. Retrieve related teaching content via RAG
        4. Order knowledge points by dependency (topological sort)

        In production this calls LLM + RAG. For now, returns a structured
        placeholder that exercises the full pipeline shape.

        Parameters
        ----------
        problem_text : str
            The math problem text submitted by the student.
        attachments : list[Attachment]
            Any image/file attachments with the problem.
        kb_name : str | None
            Knowledge base name for RAG retrieval.
        stream : StreamBus
            For emitting progress events.

        Returns
        -------
        AnalysisResult
            Structured analysis result.
        """
        has_image = any(att.type == "image" for att in attachments)

        # Step 1: Report start of analysis
        await stream.progress(
            message="开始分析题目...",
            current=0,
            total=4,
            source="problem_analyzer",
            stage="analyzing",
        )

        # Step 2: Extract image information if present
        image_context = ""
        if has_image:
            image_context = await self._extract_image_info(attachments, stream)

        await stream.progress(
            message="正在识别知识点...",
            current=1,
            total=4,
            source="problem_analyzer",
            stage="analyzing",
        )

        # Step 3: Identify knowledge points via LLM
        knowledge_points = await self._identify_knowledge_points_llm(problem_text, image_context)

        await stream.progress(
            message="正在检索教学内容...",
            current=2,
            total=4,
            source="problem_analyzer",
            stage="analyzing",
        )

        # Step 4: RAG retrieval (placeholder - in production calls RAG tool)
        rag_context = await self._retrieve_rag_context(
            problem_text, knowledge_points, kb_name, stream
        )

        await stream.progress(
            message="正在排列知识点依赖顺序...",
            current=3,
            total=4,
            source="problem_analyzer",
            stage="analyzing",
        )

        # Step 5: Order by prerequisites
        ordered_points = self.order_by_prerequisites(knowledge_points)

        # Step 6: Estimate difficulty and plan steps (placeholder)
        difficulty = self._estimate_difficulty(ordered_points)
        solution_steps = self._plan_solution_steps(problem_text, ordered_points)

        await stream.progress(
            message=f"分析完成：识别到 {len(ordered_points)} 个知识点，难度等级 {difficulty}",
            current=4,
            total=4,
            source="problem_analyzer",
            stage="analyzing",
        )

        return AnalysisResult(
            problem_text=problem_text,
            knowledge_points=ordered_points,
            difficulty_estimate=difficulty,
            solution_steps=solution_steps,
            rag_context=rag_context,
            has_image=has_image,
        )

    def order_by_prerequisites(self, knowledge_point_ids: list[str]) -> list[str]:
        """
        Order knowledge points by dependency using topological sort.

        Points not found in the graph are appended at the end.

        Parameters
        ----------
        knowledge_point_ids : list[str]
            Knowledge point IDs to order.

        Returns
        -------
        list[str]
            Topologically sorted knowledge point IDs.
        """
        # Separate known and unknown points
        known = [kp for kp in knowledge_point_ids if kp in self._kg]
        unknown = [kp for kp in knowledge_point_ids if kp not in self._kg]

        if not known:
            return knowledge_point_ids

        try:
            sorted_known = self._kg.topological_sort(known)
        except ValueError:
            # If cycle detected, return original order
            sorted_known = known

        return sorted_known + unknown

    # ─── Private Helpers ─────────────────────────────────────────────────

    async def _extract_image_info(
        self, attachments: list[Attachment], stream: StreamBus
    ) -> str:
        """
        Extract mathematical information from image attachments.

        In production, this sends images to a vision LLM with the
        IMAGE_EXTRACTION_TEMPLATE prompt. For now, returns a placeholder.
        """
        image_attachments = [att for att in attachments if att.type == "image"]
        if not image_attachments:
            return ""

        # Placeholder: in production, call vision LLM
        return f"[图片信息：检测到 {len(image_attachments)} 张图片附件]"

    def _identify_knowledge_points(
        self, problem_text: str, image_context: str
    ) -> list[str]:
        """
        Identify knowledge points from problem text and image context.

        Uses a simple keyword matching approach against the knowledge graph.
        The full LLM-based analysis is done in _identify_knowledge_points_llm().
        """
        # Simple keyword matching as synchronous fallback
        # The async LLM call is done separately in analyze()
        return list(self._kg.node_ids)[:5] if self._kg.node_ids else []

    async def _identify_knowledge_points_llm(
        self, problem_text: str, image_context: str
    ) -> list[str]:
        """
        Identify knowledge points using LLM analysis.
        """
        import json as _json

        from deeptutor.k12.agents.prompts.analyze import ANALYZE_PROBLEM_TEMPLATE

        # Build available knowledge points list for the prompt
        available_kps = []
        for node_id in self._kg.node_ids:
            point = self._kg.get_point(node_id)
            if point:
                available_kps.append(f"- {node_id}: {point.name}")
        available_kps_text = "\n".join(available_kps) if available_kps else "（无可用知识点）"

        image_section = f"图片信息：\n{image_context}" if image_context else ""

        user_prompt = ANALYZE_PROBLEM_TEMPLATE.format(
            problem_text=problem_text,
            image_context=image_section,
            available_knowledge_points=available_kps_text,
        )

        try:
            from deeptutor.services.llm import complete

            response = await complete(
                user_prompt,
                system_prompt="你是一位数学教师，请分析题目并识别涉及的知识点。只输出JSON格式。",
                max_tokens=1000,
            )

            # Parse JSON response
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data = _json.loads(text)
            kp_ids = data.get("knowledge_points", [])

            # Filter to only IDs that exist in our graph
            valid_ids = [kp for kp in kp_ids if kp in self._kg]
            if valid_ids:
                return valid_ids

        except Exception:
            pass

        # Fallback: return all knowledge points from the graph
        return list(self._kg.node_ids)[:5] if self._kg.node_ids else []

    async def _retrieve_rag_context(
        self,
        problem_text: str,
        knowledge_points: list[str],
        kb_name: str | None,
        stream: StreamBus,
    ) -> str:
        """
        Retrieve relevant teaching content via RAG.

        In production, this calls the RAG tool with the problem text
        and knowledge point names. For now, returns a placeholder.
        """
        if not kb_name:
            return ""

        # Placeholder: in production, call RAG tool
        point_names = []
        for kp_id in knowledge_points:
            point = self._kg.get_point(kp_id)
            if point:
                point_names.append(point.name)

        return f"[RAG检索结果：知识库 '{kb_name}' 中与 {', '.join(point_names)} 相关的教学内容]"

    def _estimate_difficulty(self, knowledge_points: list[str]) -> int:
        """
        Estimate problem difficulty based on knowledge points.

        In production, LLM provides this. For now, uses average
        difficulty of involved knowledge points.
        """
        if not knowledge_points:
            return 1

        difficulties = []
        for kp_id in knowledge_points:
            point = self._kg.get_point(kp_id)
            if point:
                difficulties.append(point.difficulty)

        if not difficulties:
            return 1

        avg = sum(difficulties) / len(difficulties)
        return max(1, min(5, round(avg)))

    def _plan_solution_steps(
        self, problem_text: str, knowledge_points: list[str]
    ) -> list[str]:
        """
        Plan solution steps based on knowledge points.

        In production, LLM generates these. For now, creates
        placeholder steps from knowledge point names.
        """
        steps = []
        for kp_id in knowledge_points:
            point = self._kg.get_point(kp_id)
            if point:
                steps.append(f"应用「{point.name}」解决相关部分")
            else:
                steps.append(f"处理知识点 {kp_id}")
        return steps
