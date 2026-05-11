"""
Unit tests for PracticeGenerator.

Tests cover:
- Empty weak knowledge points fallback/redistribution behavior
- Difficulty boundary constraints (never below 1, never above 5)
- Problems with invalid reference answers are discarded
"""

import asyncio

import pytest

from deeptutor.k12.knowledge_graph import KnowledgeGraph, KnowledgePointNode
from deeptutor.k12.models import MasteryRecord, PracticeProblem, StudentProfileData
from deeptutor.k12.practice_generator import PracticeGenerator


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _make_kg(point_ids: list[str]) -> KnowledgeGraph:
    """Create a KnowledgeGraph with the given point IDs."""
    kg = KnowledgeGraph()
    for pid in point_ids:
        node = KnowledgePointNode(
            id=pid,
            name=f"Point {pid}",
            grade="7",
            semester="1",
            chapter="1",
            difficulty=3,
            prerequisites=[],
        )
        kg._nodes[pid] = node
        kg._edges[pid] = []
    return kg


def _make_profile(mastery_map: dict[str, float]) -> StudentProfileData:
    """Create a StudentProfileData with given mastery scores."""
    mastery = {
        pid: MasteryRecord(
            knowledge_point_id=pid, score=score, last_updated=0.0, attempt_count=1
        )
        for pid, score in mastery_map.items()
    }
    return StudentProfileData(
        student_id="test_student",
        grade="7",
        semester="1",
        textbook_version="人教版",
        mastery=mastery,
    )


# ─── Test: Empty weak knowledge points redistribution ────────────────────────


class TestEmptyWeakPointsRedistribution:
    """Test behavior when there are no weak knowledge points."""

    def test_no_weak_points_redistributes_to_review_and_challenge(self):
        """When no weak points exist, problems should come from review/challenge."""
        # All points have mastery >= 0.4 (no weak points)
        all_ids = [f"kp_{i}" for i in range(6)]
        review_ids = all_ids[:4]  # mastery 0.5
        challenge_ids = all_ids[4:]  # mastery 0.8

        mastery_map = {}
        for pid in review_ids:
            mastery_map[pid] = 0.5
        for pid in challenge_ids:
            mastery_map[pid] = 0.8

        kg = _make_kg(all_ids)
        profile = _make_profile(mastery_map)
        generator = PracticeGenerator(kg)

        problems = asyncio.get_event_loop().run_until_complete(
            generator.generate_practice_set(profile, count=10)
        )

        # No weak problems should exist
        weak_problems = [p for p in problems if p.category == "weak"]
        assert len(weak_problems) == 0, "Should have no weak problems when no weak points"

        # All problems should be review or challenge
        for p in problems:
            assert p.category in ("review", "challenge")

        # Should still generate problems
        assert len(problems) > 0

    def test_only_review_points_fills_all_with_review(self):
        """When only review points exist, all problems should be review."""
        review_ids = [f"review_{i}" for i in range(5)]
        mastery_map = {pid: 0.5 for pid in review_ids}

        kg = _make_kg(review_ids)
        profile = _make_profile(mastery_map)
        generator = PracticeGenerator(kg)

        problems = asyncio.get_event_loop().run_until_complete(
            generator.generate_practice_set(profile, count=10)
        )

        # All should be review
        for p in problems:
            assert p.category == "review"

    def test_only_challenge_points_fills_all_with_challenge(self):
        """When only challenge points exist, all problems should be challenge."""
        challenge_ids = [f"challenge_{i}" for i in range(5)]
        mastery_map = {pid: 0.85 for pid in challenge_ids}

        kg = _make_kg(challenge_ids)
        profile = _make_profile(mastery_map)
        generator = PracticeGenerator(kg)

        problems = asyncio.get_event_loop().run_until_complete(
            generator.generate_practice_set(profile, count=10)
        )

        # All should be challenge
        for p in problems:
            assert p.category == "challenge"


# ─── Test: Difficulty boundary constraints ───────────────────────────────────


class TestDifficultyBoundary:
    """Test that difficulty adjustment never goes below 1 or above 5."""

    def test_difficulty_does_not_go_below_1(self):
        """Difficulty at 1 with consecutive wrong should stay at 1."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        result = generator.adjust_difficulty(
            current_difficulty=1,
            consecutive_correct=0,
            consecutive_wrong=5,
        )
        assert result == 1, f"Difficulty should not go below 1, got {result}"

    def test_difficulty_does_not_go_above_5(self):
        """Difficulty at 5 with consecutive correct should stay at 5."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        result = generator.adjust_difficulty(
            current_difficulty=5,
            consecutive_correct=10,
            consecutive_wrong=0,
        )
        assert result == 5, f"Difficulty should not go above 5, got {result}"

    def test_difficulty_increases_on_3_correct(self):
        """Difficulty increases by 1 after 3 consecutive correct."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        result = generator.adjust_difficulty(
            current_difficulty=3,
            consecutive_correct=3,
            consecutive_wrong=0,
        )
        assert result == 4

    def test_difficulty_decreases_on_2_wrong(self):
        """Difficulty decreases by 1 after 2 consecutive wrong."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        result = generator.adjust_difficulty(
            current_difficulty=3,
            consecutive_correct=0,
            consecutive_wrong=2,
        )
        assert result == 2

    def test_difficulty_no_change_below_thresholds(self):
        """Difficulty stays the same when below both thresholds."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        result = generator.adjust_difficulty(
            current_difficulty=3,
            consecutive_correct=2,
            consecutive_wrong=1,
        )
        assert result == 3

    def test_difficulty_correct_takes_priority_over_wrong(self):
        """When both thresholds met, consecutive_correct >= 3 takes priority."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        # Both conditions met: correct >= 3 AND wrong >= 2
        # The implementation checks correct first
        result = generator.adjust_difficulty(
            current_difficulty=3,
            consecutive_correct=3,
            consecutive_wrong=2,
        )
        assert result == 4, "Correct streak should take priority"


# ─── Test: Validation failure discards problems ──────────────────────────────


class TestValidationDiscard:
    """Test that problems with invalid reference answers are discarded."""

    def test_empty_reference_answer_discarded(self):
        """Problems with empty reference_answer should be discarded."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        # Create a problem with empty reference answer
        problem = PracticeProblem(
            problem_text="Test problem",
            knowledge_points=["kp_1"],
            difficulty=3,
            reference_answer="",
            category="weak",
        )

        result = asyncio.get_event_loop().run_until_complete(
            generator.validate_answer(problem)
        )
        assert result is False, "Empty reference_answer should fail validation"

    def test_whitespace_only_reference_answer_discarded(self):
        """Problems with whitespace-only reference_answer should be discarded."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        problem = PracticeProblem(
            problem_text="Test problem",
            knowledge_points=["kp_1"],
            difficulty=3,
            reference_answer="   \t\n  ",
            category="weak",
        )

        result = asyncio.get_event_loop().run_until_complete(
            generator.validate_answer(problem)
        )
        assert result is False, "Whitespace-only reference_answer should fail validation"

    def test_valid_reference_answer_passes(self):
        """Problems with valid reference_answer should pass validation."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        problem = PracticeProblem(
            problem_text="Test problem",
            knowledge_points=["kp_1"],
            difficulty=3,
            reference_answer="x = 5",
            category="weak",
        )

        result = asyncio.get_event_loop().run_until_complete(
            generator.validate_answer(problem)
        )
        assert result is True, "Valid reference_answer should pass validation"

    def test_invalid_problems_excluded_from_practice_set(self):
        """Practice set should not contain problems that fail validation."""
        # We'll create a custom generator that produces some invalid problems
        all_ids = [f"kp_{i}" for i in range(5)]
        kg = _make_kg(all_ids)
        mastery_map = {pid: 0.2 for pid in all_ids}  # All weak
        profile = _make_profile(mastery_map)

        # Subclass to inject invalid problems
        class TestGenerator(PracticeGenerator):
            def _generate_problems(self, kp_ids, count, category):
                if not kp_ids or count <= 0:
                    return []
                problems = []
                for i in range(count):
                    kp_id = kp_ids[i % len(kp_ids)]
                    # Every other problem has empty reference_answer
                    ref_answer = "" if i % 2 == 0 else f"answer_{i}"
                    problems.append(
                        PracticeProblem(
                            problem_text=f"Problem {i}",
                            knowledge_points=[kp_id],
                            difficulty=3,
                            reference_answer=ref_answer,
                            category=category,
                        )
                    )
                return problems

        generator = TestGenerator(kg)
        problems = asyncio.get_event_loop().run_until_complete(
            generator.generate_practice_set(profile, count=10)
        )

        # All returned problems should have valid reference answers
        for p in problems:
            assert p.reference_answer.strip(), (
                f"Problem with empty reference_answer should not be in result"
            )


# ─── Test: select_knowledge_points categorization ────────────────────────────


class TestSelectKnowledgePoints:
    """Test knowledge point categorization."""

    def test_categorizes_correctly(self):
        """Points are categorized by mastery score thresholds."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        mastery_map = {
            "weak_1": 0.1,
            "weak_2": 0.3,
            "review_1": 0.4,
            "review_2": 0.7,
            "challenge_1": 0.8,
            "challenge_2": 0.95,
        }
        profile = _make_profile(mastery_map)

        weak, review, challenge = generator.select_knowledge_points(profile, 10)

        assert set(weak) == {"weak_1", "weak_2"}
        assert set(review) == {"review_1", "review_2"}
        assert set(challenge) == {"challenge_1", "challenge_2"}

    def test_empty_profile_returns_empty_lists(self):
        """Empty mastery profile returns empty category lists."""
        kg = KnowledgeGraph()
        generator = PracticeGenerator(kg)

        profile = _make_profile({})
        weak, review, challenge = generator.select_knowledge_points(profile, 10)

        assert weak == []
        assert review == []
        assert challenge == []
