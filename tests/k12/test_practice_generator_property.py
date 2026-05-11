# Feature: k12-math-guided-tutoring, Property 9: 练习题集分布比例正确
# Feature: k12-math-guided-tutoring, Property 10: 难度调整遵循连续答题规则
# Feature: k12-math-guided-tutoring, Property 11: 练习题结构完整性
"""
Property-based tests for PracticeGenerator.

Tests cover:
- Property 9: Practice set distribution ratio correctness
- Property 10: Difficulty adjustment follows consecutive answer rules
- Property 11: Practice problem structure completeness
"""

import asyncio

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from deeptutor.k12.knowledge_graph import KnowledgeGraph, KnowledgePointNode
from deeptutor.k12.models import MasteryRecord, StudentProfileData, PracticeProblem
from deeptutor.k12.practice_generator import PracticeGenerator


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_knowledge_graph(point_ids: list[str]) -> KnowledgeGraph:
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


def _make_profile_with_categories(
    weak_ids: list[str],
    review_ids: list[str],
    challenge_ids: list[str],
) -> StudentProfileData:
    """Create a StudentProfileData with specified category distributions."""
    mastery: dict[str, MasteryRecord] = {}
    for pid in weak_ids:
        mastery[pid] = MasteryRecord(
            knowledge_point_id=pid, score=0.2, last_updated=0.0, attempt_count=1
        )
    for pid in review_ids:
        mastery[pid] = MasteryRecord(
            knowledge_point_id=pid, score=0.55, last_updated=0.0, attempt_count=1
        )
    for pid in challenge_ids:
        mastery[pid] = MasteryRecord(
            knowledge_point_id=pid, score=0.85, last_updated=0.0, attempt_count=1
        )
    return StudentProfileData(
        student_id="test_student",
        grade="7",
        semester="1",
        textbook_version="人教版",
        mastery=mastery,
    )


# ─── Strategies ──────────────────────────────────────────────────────────────


# Strategy for generating knowledge point IDs
kp_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=3,
    max_size=15,
)


@st.composite
def profile_with_all_categories_strategy(draw):
    """Generate a profile that has weak, review, and challenge knowledge points."""
    # Ensure at least 2 points in each category for meaningful distribution
    num_weak = draw(st.integers(min_value=2, max_value=8))
    num_review = draw(st.integers(min_value=1, max_value=5))
    num_challenge = draw(st.integers(min_value=1, max_value=4))

    # Generate unique IDs
    all_ids = draw(
        st.lists(
            kp_id_st,
            min_size=num_weak + num_review + num_challenge,
            max_size=num_weak + num_review + num_challenge,
            unique=True,
        )
    )

    weak_ids = all_ids[:num_weak]
    review_ids = all_ids[num_weak : num_weak + num_review]
    challenge_ids = all_ids[num_weak + num_review :]

    # Build mastery with appropriate scores
    mastery: dict[str, MasteryRecord] = {}
    for pid in weak_ids:
        score = draw(st.floats(min_value=0.0, max_value=0.39))
        mastery[pid] = MasteryRecord(
            knowledge_point_id=pid, score=score, last_updated=0.0, attempt_count=1
        )
    for pid in review_ids:
        score = draw(st.floats(min_value=0.4, max_value=0.7))
        mastery[pid] = MasteryRecord(
            knowledge_point_id=pid, score=score, last_updated=0.0, attempt_count=1
        )
    for pid in challenge_ids:
        score = draw(st.floats(min_value=0.71, max_value=1.0))
        mastery[pid] = MasteryRecord(
            knowledge_point_id=pid, score=score, last_updated=0.0, attempt_count=1
        )

    profile = StudentProfileData(
        student_id="test_student",
        grade="7",
        semester="1",
        textbook_version="人教版",
        mastery=mastery,
    )

    # Build knowledge graph with all points
    kg = _make_knowledge_graph(all_ids)

    return profile, kg


# ─── Property 9: 练习题集分布比例正确 ────────────────────────────────────────


@given(data=profile_with_all_categories_strategy(), count=st.integers(min_value=10, max_value=30))
@settings(max_examples=100)
def test_practice_set_distribution_ratio(data, count: int):
    """
    Property 9: For any student profile with weak knowledge points,
    the generated practice set should have approximately:
    - 70% weak problems (±10% tolerance)
    - 20% review problems (±10% tolerance)
    - 10% challenge problems (±10% tolerance)

    Tolerance is applied as absolute percentage points.

    **Validates: Requirements 7.1**
    """
    profile, kg = data
    generator = PracticeGenerator(kg)

    # Generate practice set
    problems = asyncio.get_event_loop().run_until_complete(
        generator.generate_practice_set(profile, count)
    )

    # Count by category
    total = len(problems)
    assume(total >= 10)  # Need enough problems for meaningful ratio check

    weak_count = sum(1 for p in problems if p.category == "weak")
    review_count = sum(1 for p in problems if p.category == "review")
    challenge_count = sum(1 for p in problems if p.category == "challenge")

    # Verify distribution with ±10% tolerance (absolute percentage points)
    weak_ratio = weak_count / total
    review_ratio = review_count / total
    challenge_ratio = challenge_count / total

    assert 0.60 <= weak_ratio <= 0.80, (
        f"Weak ratio {weak_ratio:.2f} not in [0.60, 0.80]. "
        f"Counts: weak={weak_count}, review={review_count}, challenge={challenge_count}, total={total}"
    )
    assert 0.10 <= review_ratio <= 0.30, (
        f"Review ratio {review_ratio:.2f} not in [0.10, 0.30]. "
        f"Counts: weak={weak_count}, review={review_count}, challenge={challenge_count}, total={total}"
    )
    assert 0.00 <= challenge_ratio <= 0.20, (
        f"Challenge ratio {challenge_ratio:.2f} not in [0.00, 0.20]. "
        f"Counts: weak={weak_count}, review={review_count}, challenge={challenge_count}, total={total}"
    )


# ─── Property 10: 难度调整遵循连续答题规则 ───────────────────────────────────


@given(
    current_difficulty=st.integers(min_value=1, max_value=5),
    consecutive_correct=st.integers(min_value=0, max_value=20),
    consecutive_wrong=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=100)
def test_difficulty_adjustment_rules(
    current_difficulty: int,
    consecutive_correct: int,
    consecutive_wrong: int,
):
    """
    Property 10: For any difficulty in [1,5]:
    - consecutive_correct >= 3 → difficulty + 1 (max 5)
    - consecutive_wrong >= 2 → difficulty - 1 (min 1)
    - Result always in [1, 5]

    Note: consecutive_correct and consecutive_wrong are mutually exclusive
    in practice (one resets when the other increments), but we test all
    combinations to verify boundary behavior.

    **Validates: Requirements 7.3, 7.4**
    """
    kg = KnowledgeGraph()
    generator = PracticeGenerator(kg)

    new_difficulty = generator.adjust_difficulty(
        current_difficulty, consecutive_correct, consecutive_wrong
    )

    # Result always in [1, 5]
    assert 1 <= new_difficulty <= 5, (
        f"Difficulty {new_difficulty} out of bounds [1, 5]. "
        f"current={current_difficulty}, correct={consecutive_correct}, wrong={consecutive_wrong}"
    )

    # Verify specific rules
    if consecutive_correct >= 3:
        expected = min(5, current_difficulty + 1)
        assert new_difficulty == expected, (
            f"Expected difficulty {expected} after {consecutive_correct} correct, "
            f"got {new_difficulty} (current={current_difficulty})"
        )
    elif consecutive_wrong >= 2:
        expected = max(1, current_difficulty - 1)
        assert new_difficulty == expected, (
            f"Expected difficulty {expected} after {consecutive_wrong} wrong, "
            f"got {new_difficulty} (current={current_difficulty})"
        )
    else:
        # No change
        assert new_difficulty == current_difficulty, (
            f"Expected no change (difficulty={current_difficulty}), "
            f"got {new_difficulty} (correct={consecutive_correct}, wrong={consecutive_wrong})"
        )


# ─── Property 11: 练习题结构完整性 ──────────────────────────────────────────


@given(data=profile_with_all_categories_strategy(), count=st.integers(min_value=5, max_value=20))
@settings(max_examples=100)
def test_practice_problem_structure_completeness(data, count: int):
    """
    Property 11: Every generated PracticeProblem must have:
    - Non-empty problem_text
    - At least one knowledge_point
    - Valid difficulty in [1, 5]
    - Non-empty reference_answer
    - Valid category ("weak", "review", or "challenge")

    **Validates: Requirements 7.5**
    """
    profile, kg = data
    generator = PracticeGenerator(kg)

    problems = asyncio.get_event_loop().run_until_complete(
        generator.generate_practice_set(profile, count)
    )

    for i, problem in enumerate(problems):
        # Non-empty problem_text
        assert problem.problem_text and problem.problem_text.strip(), (
            f"Problem {i} has empty problem_text"
        )

        # At least one knowledge point
        assert len(problem.knowledge_points) >= 1, (
            f"Problem {i} has no knowledge_points"
        )

        # Valid difficulty [1, 5]
        assert 1 <= problem.difficulty <= 5, (
            f"Problem {i} has invalid difficulty {problem.difficulty}"
        )

        # Non-empty reference_answer
        assert problem.reference_answer and problem.reference_answer.strip(), (
            f"Problem {i} has empty reference_answer"
        )

        # Valid category
        assert problem.category in ("weak", "review", "challenge"), (
            f"Problem {i} has invalid category '{problem.category}'"
        )
