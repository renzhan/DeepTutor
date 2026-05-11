"""
Knowledge Graph Service
=======================

Loads knowledge point data from JSON files and provides
graph algorithms: topological sort, dependency chain retrieval,
DAG validation, and weak point identification.

This module is separate from the Pydantic ``KnowledgeGraph`` model in
``models.py``. It provides a service layer that dynamically loads JSON
data files and exposes advanced graph operations.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lightweight node dataclass (avoids Pydantic overhead for bulk loading)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class KnowledgePointNode:
    """A single node in the knowledge graph."""

    id: str
    name: str
    grade: str
    semester: str
    chapter: str
    difficulty: int  # 1-5
    prerequisites: list[str] = field(default_factory=list)
    common_mistakes: list[str] = field(default_factory=list)
    example_templates: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeGraph — graph service
# ─────────────────────────────────────────────────────────────────────────────


class KnowledgeGraph:
    """
    Knowledge graph manager.

    Loads JSON data files from a data directory, provides knowledge point
    queries, prerequisite dependency chain retrieval, topological sort,
    DAG validation, and weak point identification.

    Usage::

        kg = KnowledgeGraph()
        kg.load(Path("deeptutor/k12/data"))
        chain = kg.get_prerequisites_chain("solve_linear_equation")
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        self._nodes: dict[str, KnowledgePointNode] = {}
        self._edges: dict[str, list[str]] = {}  # node_id -> list of prerequisite IDs

        if data_dir is not None:
            self.load(data_dir)

    # ─── Loading ─────────────────────────────────────────────────────────

    def load(self, data_dir: Path) -> None:
        """Load all JSON data files from *data_dir*.

        Each ``.json`` file is expected to contain a ``knowledge_points``
        array following the schema defined in ``data/README.md``.
        Invalid files are skipped with a warning log.
        """
        data_path = Path(data_dir)
        if not data_path.is_dir():
            logger.warning("Data directory does not exist: %s", data_path)
            return

        json_files = sorted(data_path.glob("*.json"))
        if not json_files:
            logger.info("No JSON files found in %s", data_path)
            return

        for filepath in json_files:
            try:
                self._load_file(filepath)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning(
                    "Skipping invalid data file %s: %s", filepath.name, exc
                )

    def _load_file(self, filepath: Path) -> None:
        """Parse a single JSON data file and add its knowledge points."""
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        points = data.get("knowledge_points", [])
        for raw in points:
            node = KnowledgePointNode(
                id=raw["id"],
                name=raw["name"],
                grade=str(raw.get("grade", "")),
                semester=str(raw.get("semester", "")),
                chapter=str(raw.get("chapter", "")),
                difficulty=int(raw.get("difficulty", 1)),
                prerequisites=list(raw.get("prerequisites", [])),
                common_mistakes=list(raw.get("common_mistakes", [])),
                example_templates=list(raw.get("example_templates", [])),
                tags=list(raw.get("tags", [])),
            )
            self._nodes[node.id] = node
            self._edges[node.id] = node.prerequisites

    # ─── Queries ─────────────────────────────────────────────────────────

    def get_point(self, point_id: str) -> KnowledgePointNode | None:
        """Get a single knowledge point by ID, or ``None`` if not found."""
        return self._nodes.get(point_id)

    def get_prerequisites_chain(self, point_id: str) -> list[str]:
        """Return the complete prerequisite dependency chain for *point_id*.

        Uses BFS to collect all transitive prerequisites, then returns
        them in topological order (prerequisites before dependents).
        The result does NOT include *point_id* itself.

        Returns an empty list if *point_id* is not in the graph or has
        no prerequisites.
        """
        if point_id not in self._nodes:
            return []

        # BFS to find all transitive prerequisites
        visited: set[str] = set()
        queue: deque[str] = deque()

        # Seed with direct prerequisites
        for prereq_id in self._edges.get(point_id, []):
            if prereq_id in self._nodes and prereq_id not in visited:
                visited.add(prereq_id)
                queue.append(prereq_id)

        while queue:
            current = queue.popleft()
            for prereq_id in self._edges.get(current, []):
                if prereq_id in self._nodes and prereq_id not in visited:
                    visited.add(prereq_id)
                    queue.append(prereq_id)

        if not visited:
            return []

        # Return in topological order
        return self.topological_sort(list(visited))

    # ─── Graph Algorithms ────────────────────────────────────────────────

    def topological_sort(self, point_ids: list[str]) -> list[str]:
        """Topological sort of a subset of knowledge points using Kahn's algorithm.

        Returns a list where prerequisites appear before their dependents.

        Parameters
        ----------
        point_ids : list[str]
            The subset of node IDs to sort. Only edges within this subset
            are considered.

        Returns
        -------
        list[str]
            Topologically sorted node IDs.

        Raises
        ------
        ValueError
            If a cycle is detected within the given subset.
        """
        subset = set(point_ids)
        if not subset:
            return []

        # Build in-degree map restricted to the subset
        in_degree: dict[str, int] = {nid: 0 for nid in subset}
        # adjacency: prerequisite -> list of dependents (within subset)
        adjacency: dict[str, list[str]] = {nid: [] for nid in subset}

        for nid in subset:
            for prereq_id in self._edges.get(nid, []):
                if prereq_id in subset:
                    in_degree[nid] += 1
                    adjacency[prereq_id].append(nid)

        # Kahn's algorithm
        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for dependent in adjacency[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(subset):
            raise ValueError(
                "Cycle detected in knowledge graph subset: "
                f"sorted {len(result)} of {len(subset)} nodes"
            )

        return result

    def is_dag(self) -> bool:
        """Verify the entire graph is a directed acyclic graph.

        Returns ``True`` if topological sort succeeds on all nodes
        (no cycles), ``False`` otherwise.
        """
        if not self._nodes:
            return True

        try:
            self.topological_sort(list(self._nodes.keys()))
            return True
        except ValueError:
            return False

    def get_weak_points(self, mastery_scores: dict[str, float]) -> list[str]:
        """Return knowledge point IDs with mastery score below 0.4.

        Parameters
        ----------
        mastery_scores : dict[str, float]
            Mapping of knowledge point ID to mastery score (0.0–1.0).

        Returns
        -------
        list[str]
            IDs of knowledge points that exist in the graph and have
            mastery < 0.4.
        """
        weak: list[str] = []
        for point_id, score in mastery_scores.items():
            if point_id in self._nodes and score < 0.4:
                weak.append(point_id)
        return weak

    # ─── Properties ──────────────────────────────────────────────────────

    @property
    def nodes(self) -> dict[str, KnowledgePointNode]:
        """All loaded knowledge point nodes."""
        return self._nodes

    @property
    def node_ids(self) -> list[str]:
        """List of all loaded knowledge point IDs."""
        return list(self._nodes.keys())

    @property
    def edges(self) -> dict[str, list[str]]:
        """Prerequisite edges: node_id -> list of prerequisite IDs."""
        return self._edges

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, point_id: str) -> bool:
        return point_id in self._nodes
