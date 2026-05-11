"""
Unit tests for KnowledgeGraph module.

Tests cover:
- Loading valid/invalid JSON files
- Topological sort for empty, single-node, and multi-node graphs
- Cycle detection
- Weak point identification

Requirements: 6.2, 6.3, 6.4
"""

import json
from pathlib import Path

import pytest

from deeptutor.k12.knowledge_graph import KnowledgeGraph, KnowledgePointNode


# ─────────────────────────────────────────────────────────────────────────────
# Loading valid JSON files
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadValidJSON:
    """Test loading from the example data directory."""

    def test_loads_example_data(self):
        """Test loading from deeptutor/k12/data/ loads 5 nodes."""
        data_dir = Path("deeptutor/k12/data")
        kg = KnowledgeGraph(data_dir=data_dir)
        assert len(kg) == 5

    def test_specific_node_exists(self):
        """Test that specific nodes exist after loading."""
        data_dir = Path("deeptutor/k12/data")
        kg = KnowledgeGraph(data_dir=data_dir)
        assert "rational_numbers.concept" in kg
        assert "rational_numbers.number_line" in kg
        assert "rational_numbers.absolute_value" in kg

    def test_loaded_graph_is_dag(self):
        """Test that the loaded example data forms a valid DAG."""
        data_dir = Path("deeptutor/k12/data")
        kg = KnowledgeGraph(data_dir=data_dir)
        assert kg.is_dag() is True


# ─────────────────────────────────────────────────────────────────────────────
# Loading invalid JSON files
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadInvalidJSON:
    """Test loading invalid JSON files (malformed JSON is skipped)."""

    def test_invalid_json_skipped(self, tmp_path: Path):
        """Test that malformed JSON files are skipped without raising."""
        invalid_file = tmp_path / "bad_data.json"
        invalid_file.write_text("{this is not valid json!!!", encoding="utf-8")

        kg = KnowledgeGraph()
        kg.load(tmp_path)  # Should not raise
        assert len(kg) == 0

    def test_mixed_valid_and_invalid_files(self, tmp_path: Path):
        """Test that valid files are loaded even when invalid files exist."""
        # Write a valid file
        valid_data = {
            "knowledge_points": [
                {
                    "id": "test_node",
                    "name": "Test Node",
                    "grade": "7",
                    "semester": "1",
                    "chapter": "Ch1",
                    "difficulty": 1,
                    "prerequisites": [],
                    "common_mistakes": [],
                    "example_templates": [],
                    "tags": [],
                }
            ]
        }
        valid_file = tmp_path / "valid.json"
        valid_file.write_text(json.dumps(valid_data), encoding="utf-8")

        # Write an invalid file
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("not json at all {{{", encoding="utf-8")

        kg = KnowledgeGraph()
        kg.load(tmp_path)
        assert len(kg) == 1
        assert "test_node" in kg


# ─────────────────────────────────────────────────────────────────────────────
# Loading from non-existent directory
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadNonExistentDirectory:
    """Test loading from a non-existent path."""

    def test_nonexistent_directory_does_not_raise(self):
        """Test that loading from a non-existent path doesn't raise."""
        kg = KnowledgeGraph()
        kg.load(Path("/nonexistent/path/that/does/not/exist"))
        assert len(kg) == 0

    def test_nonexistent_directory_graph_is_empty(self, tmp_path: Path):
        """Test that the graph is empty after loading from non-existent subdir."""
        kg = KnowledgeGraph(data_dir=tmp_path / "no_such_dir")
        assert len(kg) == 0
        assert kg.node_ids == []


# ─────────────────────────────────────────────────────────────────────────────
# Empty graph topological sort
# ─────────────────────────────────────────────────────────────────────────────


class TestEmptyGraphTopologicalSort:
    """Test topological sort on an empty graph."""

    def test_topological_sort_empty_list(self):
        """Test that topological_sort([]) returns []."""
        kg = KnowledgeGraph()
        assert kg.topological_sort([]) == []

    def test_empty_graph_is_dag(self):
        """Test that an empty graph is considered a valid DAG."""
        kg = KnowledgeGraph()
        assert kg.is_dag() is True


# ─────────────────────────────────────────────────────────────────────────────
# Single node graph
# ─────────────────────────────────────────────────────────────────────────────


class TestSingleNodeGraph:
    """Test graph with one node and no prerequisites."""

    def _make_single_node_graph(self) -> KnowledgeGraph:
        kg = KnowledgeGraph()
        kg._nodes["A"] = KnowledgePointNode(
            id="A",
            name="Node A",
            grade="7",
            semester="1",
            chapter="Ch1",
            difficulty=1,
            prerequisites=[],
        )
        kg._edges["A"] = []
        return kg

    def test_topological_sort_single_node(self):
        """Test that topological_sort returns [node_id] for a single node."""
        kg = self._make_single_node_graph()
        result = kg.topological_sort(["A"])
        assert result == ["A"]

    def test_get_prerequisites_chain_single_node(self):
        """Test that get_prerequisites_chain returns [] for a node with no prereqs."""
        kg = self._make_single_node_graph()
        assert kg.get_prerequisites_chain("A") == []


# ─────────────────────────────────────────────────────────────────────────────
# Multi-node graph topological sort
# ─────────────────────────────────────────────────────────────────────────────


class TestMultiNodeTopologicalSort:
    """Test topological sort on a multi-node graph: A -> B -> C."""

    def _make_chain_graph(self) -> KnowledgeGraph:
        """Create graph: C depends on B, B depends on A."""
        kg = KnowledgeGraph()
        for node_id, prereqs in [("A", []), ("B", ["A"]), ("C", ["B"])]:
            kg._nodes[node_id] = KnowledgePointNode(
                id=node_id,
                name=f"Node {node_id}",
                grade="7",
                semester="1",
                chapter="Ch1",
                difficulty=1,
                prerequisites=prereqs,
            )
            kg._edges[node_id] = prereqs
        return kg

    def test_topological_sort_order(self):
        """Test that topological_sort returns A before B before C."""
        kg = self._make_chain_graph()
        result = kg.topological_sort(["A", "B", "C"])
        assert result.index("A") < result.index("B") < result.index("C")

    def test_get_prerequisites_chain_returns_all_ancestors(self):
        """Test that get_prerequisites_chain('C') returns ['A', 'B'] in topo order."""
        kg = self._make_chain_graph()
        chain = kg.get_prerequisites_chain("C")
        assert set(chain) == {"A", "B"}
        # A must come before B in the chain (topological order)
        assert chain.index("A") < chain.index("B")


# ─────────────────────────────────────────────────────────────────────────────
# Cycle detection
# ─────────────────────────────────────────────────────────────────────────────


class TestCycleDetection:
    """Test cycle detection: A -> B -> C -> A."""

    def _make_cyclic_graph(self) -> KnowledgeGraph:
        """Create graph with a cycle: A depends on C, B depends on A, C depends on B."""
        kg = KnowledgeGraph()
        for node_id, prereqs in [("A", ["C"]), ("B", ["A"]), ("C", ["B"])]:
            kg._nodes[node_id] = KnowledgePointNode(
                id=node_id,
                name=f"Node {node_id}",
                grade="7",
                semester="1",
                chapter="Ch1",
                difficulty=1,
                prerequisites=prereqs,
            )
            kg._edges[node_id] = prereqs
        return kg

    def test_is_dag_returns_false_for_cycle(self):
        """Test that is_dag() returns False for a cyclic graph."""
        kg = self._make_cyclic_graph()
        assert kg.is_dag() is False

    def test_topological_sort_raises_on_cycle(self):
        """Test that topological_sort raises ValueError for a cyclic graph."""
        kg = self._make_cyclic_graph()
        with pytest.raises(ValueError, match="Cycle detected"):
            kg.topological_sort(["A", "B", "C"])


# ─────────────────────────────────────────────────────────────────────────────
# get_weak_points
# ─────────────────────────────────────────────────────────────────────────────


class TestGetWeakPoints:
    """Test get_weak_points with mastery scores above and below 0.4."""

    def _make_three_node_graph(self) -> KnowledgeGraph:
        """Create a graph with 3 nodes."""
        kg = KnowledgeGraph()
        for node_id in ["X", "Y", "Z"]:
            kg._nodes[node_id] = KnowledgePointNode(
                id=node_id,
                name=f"Node {node_id}",
                grade="7",
                semester="1",
                chapter="Ch1",
                difficulty=1,
                prerequisites=[],
            )
            kg._edges[node_id] = []
        return kg

    def test_weak_points_below_threshold(self):
        """Test that nodes with mastery < 0.4 are returned as weak points."""
        kg = self._make_three_node_graph()
        mastery_scores = {"X": 0.2, "Y": 0.5, "Z": 0.1}
        weak = kg.get_weak_points(mastery_scores)
        assert set(weak) == {"X", "Z"}

    def test_weak_points_all_above_threshold(self):
        """Test that no weak points are returned when all scores >= 0.4."""
        kg = self._make_three_node_graph()
        mastery_scores = {"X": 0.4, "Y": 0.8, "Z": 0.6}
        weak = kg.get_weak_points(mastery_scores)
        assert weak == []

    def test_weak_points_ignores_unknown_nodes(self):
        """Test that nodes not in the graph are ignored."""
        kg = self._make_three_node_graph()
        mastery_scores = {"X": 0.1, "unknown_node": 0.1}
        weak = kg.get_weak_points(mastery_scores)
        assert weak == ["X"]
