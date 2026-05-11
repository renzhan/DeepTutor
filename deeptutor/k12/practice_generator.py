"""
Practice Generator
==================

Generates adaptive practice problem sets based on student mastery.
Distributes problems across weak (70%), review (20%), and challenge (10%) categories.
Adjusts difficulty based on consecutive correct/wrong answers.
Validates reference answers before including problems in the set.
"""

from __future__ import annotations

from deeptutor.k12.knowledge_graph import KnowledgeGraph
from deeptutor.k12.models import PracticeProblem, StudentProfileData, MasteryRecord


class PracticeGenerator:
    """
    Adaptive practice problem generator.

    Generates practice sets based on student mastery profile with distribution:
    - 70% weak knowledge points (mastery < 0.4)
    - 20% review (0.4 <= mastery <= 0.7)
    - 10% challenge (mastery > 0.7)

    If not enough weak points exist, redistributes to review/challenge.
    """

    def __init__(self, knowledge_graph: KnowledgeGraph):
        self._kg = knowledge_graph

    async def generate_practice_set(
        self, profile: StudentProfileData, count: int = 10
    ) -> list[PracticeProblem]:
        """
        Generate a practice set with the target distribution.

        If there are no weak knowledge points, redistributes proportionally
        to review and challenge categories.

        Each generated problem is validated; problems with invalid reference
        answers are discarded.

        Parameters
        ----------
        profile : StudentProfileData
            The student's mastery profile.
        count : int
            Target number of problems to generate.

        Returns
        -------
        list[PracticeProblem]
            Validated practice problems (may be fewer than count if
            validation discards some).
        """
        weak_kps, review_kps, challenge_kps = self.select_knowledge_points(profile, count)

        # Calculate counts per category based on available knowledge points
        if weak_kps:
            weak_count = max(1, round(count * 0.7))
            review_count = max(1, round(count * 0.2)) if review_kps else 0
            challenge_count = count - weak_count - review_count
            if challenge_count < 0:
                challenge_count = 0
                review_count = count - weak_count
        else:
            # No weak points: redistribute to review and challenge
            weak_count = 0
            if review_kps and challenge_kps:
                review_count = max(1, round(count * 0.7))
                challenge_count = count - review_count
            elif review_kps:
                review_count = count
                challenge_count = 0
            elif challenge_kps:
                review_count = 0
                challenge_count = count
            else:
                review_count = 0
                challenge_count = 0

        problems: list[PracticeProblem] = []

        # Try LLM generation first for each category
        if weak_kps and weak_count > 0:
            problems.extend(await self.generate_problems_llm(weak_kps, weak_count, "weak"))
        if review_kps and review_count > 0:
            problems.extend(await self.generate_problems_llm(review_kps, review_count, "review"))
        if challenge_kps and challenge_count > 0:
            problems.extend(await self.generate_problems_llm(challenge_kps, challenge_count, "challenge"))

        # If LLM didn't generate enough, fill with template-based
        if len(problems) < count:
            remaining = count - len(problems)
            all_kps = weak_kps + review_kps + challenge_kps
            if all_kps:
                problems.extend(self._generate_problems(all_kps, remaining, "weak"))

        # Validate and filter
        validated: list[PracticeProblem] = []
        for p in problems:
            if await self.validate_answer(p):
                validated.append(p)

        return validated[:count]

    def select_knowledge_points(
        self, profile: StudentProfileData, count: int
    ) -> tuple[list[str], list[str], list[str]]:
        """
        Categorize knowledge points by mastery level.

        Parameters
        ----------
        profile : StudentProfileData
            Student mastery profile.
        count : int
            Target problem count (unused but kept for interface consistency).

        Returns
        -------
        tuple[list[str], list[str], list[str]]
            (weak, review, challenge) knowledge point ID lists.
            - weak: mastery < 0.4
            - review: 0.4 <= mastery <= 0.7
            - challenge: mastery > 0.7
        """
        weak: list[str] = []
        review: list[str] = []
        challenge: list[str] = []

        for kp_id, record in profile.mastery.items():
            if record.score < 0.4:
                weak.append(kp_id)
            elif record.score <= 0.7:
                review.append(kp_id)
            else:
                challenge.append(kp_id)

        return weak, review, challenge

    def adjust_difficulty(
        self,
        current_difficulty: int,
        consecutive_correct: int,
        consecutive_wrong: int,
    ) -> int:
        """
        Adjust problem difficulty based on consecutive answer streaks.

        Rules:
        - 3+ consecutive correct answers → difficulty + 1 (max 5)
        - 2+ consecutive wrong answers → difficulty - 1 (min 1)
        - Otherwise → no change

        Parameters
        ----------
        current_difficulty : int
            Current difficulty level (1-5).
        consecutive_correct : int
            Number of consecutive correct answers.
        consecutive_wrong : int
            Number of consecutive wrong answers.

        Returns
        -------
        int
            New difficulty level, always in [1, 5].
        """
        new_difficulty = current_difficulty
        if consecutive_correct >= 3:
            new_difficulty = current_difficulty + 1
        elif consecutive_wrong >= 2:
            new_difficulty = current_difficulty - 1

        # Clamp to [1, 5]
        return max(1, min(5, new_difficulty))

    async def validate_answer(self, problem: PracticeProblem) -> bool:
        """
        Validate a problem's reference answer.

        In production, this would use Code_Execution_Tool to run Python code
        verifying the mathematical correctness of the reference answer.
        For now, validates that the reference_answer is non-empty after stripping.

        Parameters
        ----------
        problem : PracticeProblem
            The problem to validate.

        Returns
        -------
        bool
            True if the reference answer is valid, False otherwise.
        """
        return bool(problem.reference_answer and problem.reference_answer.strip())

    def _generate_problems(
        self, kp_ids: list[str], count: int, category: str
    ) -> list[PracticeProblem]:
        """Generate problems using templates with random numbers.

        Uses knowledge graph example_templates to create varied problems.
        """
        import random

        if not kp_ids or count <= 0:
            return []

        problems: list[PracticeProblem] = []

        for i in range(count):
            kp_id = kp_ids[i % len(kp_ids)]
            point = self._kg.get_point(kp_id)
            difficulty = point.difficulty if point else 3
            kp_name = point.name if point else kp_id

            # Use template with random numbers
            if point and point.example_templates:
                tmpl = point.example_templates[i % len(point.example_templates)]
                tmpl_text = tmpl.get("template_text", "")
                ranges = tmpl.get("variable_ranges", {})

                # Fill in random values
                filled_text = tmpl_text
                for var, rng in ranges.items():
                    if isinstance(rng, list) and len(rng) == 2:
                        val = random.randint(int(rng[0]), int(rng[1]))
                        filled_text = filled_text.replace(f"{{{var}}}", str(val))

                solution = tmpl.get("solution_template", f"运用{kp_name}的方法求解")
                tmpl_difficulty = tmpl.get("difficulty", difficulty)

                problems.append(PracticeProblem(
                    problem_text=filled_text,
                    knowledge_points=[kp_id],
                    difficulty=max(1, min(5, tmpl_difficulty)),
                    reference_answer=solution,
                    category=category,
                ))
            else:
                problems.append(PracticeProblem(
                    problem_text=f"请运用「{kp_name}」的知识解决以下问题（难度{difficulty}）",
                    knowledge_points=[kp_id],
                    difficulty=max(1, min(5, difficulty)),
                    reference_answer=f"运用{kp_name}相关方法求解",
                    category=category,
                ))

        return problems

    async def generate_problems_llm(
        self, kp_ids: list[str], count: int, category: str
    ) -> list[PracticeProblem]:
        """Generate problems using LLM for more diverse and contextual questions."""
        import json as _json

        if not kp_ids or count <= 0:
            return []

        # Build knowledge point descriptions
        kp_descriptions = []
        for kp_id in kp_ids:
            point = self._kg.get_point(kp_id)
            name = point.name if point else kp_id
            diff = point.difficulty if point else 3
            kp_descriptions.append(f"- {name}（难度{diff}/5）")

        kp_text = "\n".join(kp_descriptions)
        category_name = {"weak": "薄弱巩固", "review": "复习", "challenge": "挑战提升"}.get(category, "练习")

        prompt = (
            f"请为初中生生成{count}道数学练习题。\n\n"
            f"涉及知识点：\n{kp_text}\n\n"
            f"练习类别：{category_name}\n"
            f"要求：\n"
            f"1. 每道题要具体，包含具体数字\n"
            f"2. 题目之间要有变化，不要重复\n"
            f"3. 难度适合初中生\n"
            f"4. 输出JSON数组格式：[{{\"problem_text\": \"题目\", \"reference_answer\": \"答案\", \"knowledge_point\": \"知识点ID\"}}]\n"
            f"5. knowledge_point 从以下选择：{', '.join(kp_ids)}\n"
        )

        try:
            from deeptutor.services.llm import complete

            response = await complete(
                prompt,
                system_prompt="你是数学出题老师。只输出JSON数组，不要其他内容。",
                max_tokens=2000,
            )

            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            raw_problems = _json.loads(text)
            if isinstance(raw_problems, list):
                problems = []
                for raw in raw_problems:
                    pt = raw.get("problem_text", "")
                    ra = raw.get("reference_answer", "")
                    kp = raw.get("knowledge_point", kp_ids[0] if kp_ids else "")
                    if pt and ra:
                        point = self._kg.get_point(kp)
                        diff = point.difficulty if point else 3
                        problems.append(PracticeProblem(
                            problem_text=pt,
                            knowledge_points=[kp],
                            difficulty=max(1, min(5, diff)),
                            reference_answer=ra,
                            category=category,
                        ))
                if problems:
                    return problems[:count]

        except Exception:
            pass

        # Fallback to template-based generation
        return self._generate_problems(kp_ids, count, category)
