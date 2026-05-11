"""
Problem Analysis Prompt Templates
==================================

Prompt templates for the problem analyzer, covering:
- Problem analysis system prompt (identify knowledge points, estimate difficulty, plan steps)
- Image information extraction prompt template

Requirements: 2.1, 2.2
"""

# ─────────────────────────────────────────────────────────────────────────────
# System Prompt — Problem Analysis
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_ANALYZE = """\
你是一位经验丰富的数学教师，擅长分析数学题目并识别其中涉及的知识点。

你的职责：
- 仔细阅读题目文本，识别所有涉及的数学知识点
- 估计题目的难度等级（1-5，1为最简单，5为最难）
- 规划解题步骤，列出学生需要完成的关键步骤
- 如果题目包含图片信息，结合图片内容进行分析

输出要求：
- knowledge_points: 涉及的知识点ID列表
- difficulty_estimate: 难度等级（1-5的整数）
- solution_steps: 解题步骤描述列表（简洁明了）

关键规则：
- 识别所有相关知识点，不要遗漏
- 难度估计要考虑知识点数量、计算复杂度和思维跳跃度
- 解题步骤要按逻辑顺序排列
- 步骤描述要简洁，每步一个核心操作
"""

# ─────────────────────────────────────────────────────────────────────────────
# Problem Analysis Template
# ─────────────────────────────────────────────────────────────────────────────

ANALYZE_PROBLEM_TEMPLATE = """\
请分析以下数学题目，识别涉及的知识点、估计难度并规划解题步骤。

题目文本：
{problem_text}

{image_context}

可用知识点列表（从知识图谱中获取）：
{available_knowledge_points}

请以 JSON 格式输出，包含以下字段：
- knowledge_points: 涉及的知识点ID列表（从可用列表中选择）
- difficulty_estimate: 难度等级（1-5的整数）
- solution_steps: 解题步骤描述列表

示例输出：
{{
    "knowledge_points": ["linear_equation_one_var", "equation_solving_steps"],
    "difficulty_estimate": 2,
    "solution_steps": ["识别方程类型", "移项合并同类项", "系数化为1求解", "验证答案"]
}}
"""

# ─────────────────────────────────────────────────────────────────────────────
# Image Information Extraction Template
# ─────────────────────────────────────────────────────────────────────────────

IMAGE_EXTRACTION_TEMPLATE = """\
请仔细观察这张数学题目图片，提取其中的所有数学信息。

要求：
1. 识别图片中的文字内容（题目文本、数字、符号）
2. 识别图形元素（几何图形、坐标系、函数图像等）
3. 提取关键数学信息（已知条件、求解目标）
4. 描述图形的关键特征（角度、长度标注、特殊位置关系等）

请以结构化文本输出提取到的信息，格式如下：
- 题目文本：[从图片中识别的文字]
- 图形描述：[图形元素的描述]
- 已知条件：[从图片中提取的已知信息]
- 求解目标：[需要求解的内容]
"""

# ─────────────────────────────────────────────────────────────────────────────
# RAG Context Integration Template
# ─────────────────────────────────────────────────────────────────────────────

RAG_CONTEXT_TEMPLATE = """\
以下是从教材知识库中检索到的与本题相关的教学内容，请参考这些内容辅助分析：

{rag_content}

请结合以上教学内容，完善你对题目的分析。
"""
