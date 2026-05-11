# Feature: k12-math-guided-tutoring, Property 7: 知识图谱为有向无环图
# Feature: k12-math-guided-tutoring, Property 1: 知识点拓扑排序保持依赖序
# Feature: k12-math-guided-tutoring, Property 8: 依赖链包含所有传递前置知识点
"""
Property-based tests for KnowledgeGraph:
- DAG validation (Property 7)
- Topological sort preserves dependency order (Property 1)
- Dependency chain completeness (Property 8)

Uses pytest + Hypothesis with random DAG generation.
"""

from collections import deque

from hypothesis import given, settings
from hypothesis import strategies as st

from deeptutor.k12.knowledge_graph import KnowledgeGraph, KnowledgePointNode


# --- Helper strategy: generate a random DAG ---


@st.composite
def random_dag(draw, min_nodes=2, max_nodes=15):
    """Generate a random DAG by only allowing edges from higher-index to lower-index nodes."""
    n = draw(st.integers(min_value=min_nodes, max_value=max_nodes))
    nodes = [f"node_{i}" for i in range(n)]
    edges: dict[str, list[str]] = {}

    for i, node_id in enumerate(nodes):
        # Can only have prerequisites from earlier nodes (ensures DAG)
        possible_prereqs = nodes[:i]
        if possible_prereqs:
            num_prereqs = draw(
                st.integers(min_value=0, max_value=min(3, len(possible_prereqs)))
            )
            prereqs = draw(
                st.lists(
                    st.sampled_from(possible_prereqs),
                    min_size=num_prereqs,
                    max_size=num_prereqs,
                    unique=True,
                )
            )
        else:
            prereqs = []
        edges[node_id] = prereqs

    kg = KnowledgeGraph()
    for node_id in nodes:
        kg._nodes[node_id] = KnowledgePointNode(
            id=node_id,
            name=node_id,
            grade="7",
            semester="1",
            chapter="1",
            difficulty=1,
            prerequisites=edges[node_id],
        )
        kg._edges[node_id] = edges[node_id]

    return kg


# --- Property 7: 知识图谱为有向无环图 ---


@given(kg=random_dag())
@settings(max_examples=100)
def test_dag_validation_true_for_valid_dag(kg: KnowledgeGraph):
    """
    Property 7: A graph constructed as a DAG (edges only point to earlier nodes)
    must be recognized as a DAG by is_dag().

    **Validates: Requirements 6.2**
    """
    assert kg.is_dag() is True


@given(kg=random_dag(min_nodes=3, max_nodes=15))
@settings(max_examples=100)
def test_dag_validation_false_when_cycle_added(kg: KnowledgeGraph):
    """
    Property 7: Adding a back-edge that creates a cycle must cause is_dag()
    to return False. We find a node with prerequisites and make one of its
    ancestors depend on it, guaranteeing a cycle.

    **Validates: Requirements 6.2**
    """
    from collections import deque as _deque

    node_ids = list(kg._nodes.keys())

    # Find a node that has at least one prerequisite (so we can create a cycle)
    target_node = None
    ancestor_node = None
    for nid in node_ids:
        prereqs = kg._edges.get(nid, [])
        if prereqs:
            # nid depends on prereqs[0], so adding prereqs[0] -> nid creates a cycle
            target_node = nid
            ancestor_node = prereqs[0]
            break

    if target_node is None or ancestor_node is None:
        # No edges in the graph — build a simple 2-node cycle manually
        a, b = node_ids[0], node_ids[1]
        kg._edges[a] = [b]
        kg._nodes[a].prerequisites = [b]
        kg._edges[b] = [a]
        kg._nodes[b].prerequisites = [a]
    else:
        # Make the ancestor depend on target_node, creating a cycle:
        # target_node -> ancestor_node -> ... -> target_node
        kg._edges[ancestor_node] = kg._edges.get(ancestor_node, []) + [target_node]
        kg._nodes[ancestor_node].prerequisites = kg._edges[ancestor_node]

    assert kg.is_dag() is False


# --- Property 1: 知识点拓扑排序保持依赖序 ---


@given(kg=random_dag())
@settings(max_examples=100)
def test_topological_sort_preserves_dependency_order(kg: KnowledgeGraph):
    """
    Property 1: For any DAG, topological_sort on all nodes must produce an ordering
    where every prerequisite A of node B appears before B in the result.

    **Validates: Requirements 2.4**
    """
    all_ids = list(kg._nodes.keys())
    if not all_ids:
        return

    sorted_ids = kg.topological_sort(all_ids)

    # Build position map
    position = {node_id: idx for idx, node_id in enumerate(sorted_ids)}

    # For every node, all its prerequisites must appear earlier
    for node_id in sorted_ids:
        for prereq_id in kg._edges.get(node_id, []):
            if prereq_id in position:
                assert position[prereq_id] < position[node_id], (
                    f"Prerequisite {prereq_id} (pos {position[prereq_id]}) "
                    f"should appear before {node_id} (pos {position[node_id]})"
                )


# --- Property 8: 依赖链包含所有传递前置知识点 ---


def _compute_all_transitive_prerequisites(kg: KnowledgeGraph, point_id: str) -> set[str]:
    """BFS to compute all transitive prerequisites of a node."""
    visited: set[str] = set()
    queue: deque[str] = deque()

    for prereq_id in kg._edges.get(point_id, []):
        if prereq_id in kg._nodes and prereq_id not in visited:
            visited.add(prereq_id)
            queue.append(prereq_id)

    while queue:
        current = queue.popleft()
        for prereq_id in kg._edges.get(current, []):
            if prereq_id in kg._nodes and prereq_id not in visited:
                visited.add(prereq_id)
                queue.append(prereq_id)

    return visited


@given(kg=random_dag(), node_index=st.integers(min_value=0, max_value=100))
@settings(max_examples=100)
def test_dependency_chain_contains_all_transitive_prerequisites(
    kg: KnowledgeGraph, node_index: int
):
    """
    Property 8: For any node in the graph, get_prerequisites_chain must return
    ALL transitive prerequisites and must NOT contain the node itself.

    **Validates: Requirements 6.4**
    """
    all_ids = list(kg._nodes.keys())
    if not all_ids:
        return

    # Pick a node
    target_id = all_ids[node_index % len(all_ids)]

    # Get the chain from the implementation
    chain = kg.get_prerequisites_chain(target_id)

    # Compute expected transitive prerequisites via BFS
    expected = _compute_all_transitive_prerequisites(kg, target_id)

    # The chain must contain exactly all transitive prerequisites
    chain_set = set(chain)
    assert chain_set == expected, (
        f"For node {target_id}: chain has {chain_set}, expected {expected}. "
        f"Missing: {expected - chain_set}, Extra: {chain_set - expected}"
    )

    # The chain must NOT contain the node itself
    assert target_id not in chain, (
        f"Node {target_id} should not appear in its own prerequisite chain"
    )
