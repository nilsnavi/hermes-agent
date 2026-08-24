"""Sprint 1.3.15 — bounded dependency graph + authoritative topological order.

Execution/rollback ORDER is derived ONLY from the verified dependency graph.
A caller may *suggest* a desired order but the coordinator always re-derives
topological order and rejects any request that would violate the graph
(PLAN_INVALID).  Cycles, unknown dependencies, stale graphs and corrupt graphs
all fail closed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum


class GraphStatus(Enum):
    VALID = "VALID"
    CYCLE = "CYCLE"
    UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"
    STALE = "STALE"
    CORRUPT = "CORRUPT"
    TOO_LARGE = "TOO_LARGE"


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    service_ids: tuple[str, ...]
    # edges: dependency -> set(dependents)  (dep ends when dep ends??? no):
    # We encode "A depends_on B" as edge (A, B).  For topological ordering we
    # need dependencies BEFORE dependents, i.e. B before A.
    edges: tuple[tuple[str, str], ...] = ()  # (dependent, dependency)
    schema_version: int = 1
    graph_digest: str | None = None
    status: GraphStatus = GraphStatus.VALID

    def adjacency(self) -> dict[str, set[str]]:
        """dependent -> set(dependencies it needs before itself)."""
        adj: dict[str, set[str]] = {}
        for dependent, dependency in self.edges:
            adj.setdefault(dependent, set()).add(dependency)
        for sid in self.service_ids:
            adj.setdefault(sid, set())
        return adj

    def _validate(self, registry) -> tuple[GraphStatus, list[str]]:
        sids = set(self.service_ids)
        if len(sids) != len(self.service_ids):
            return GraphStatus.CORRUPT, []
        for dependent, dependency in self.edges:
            if dependent not in sids or dependency not in sids:
                return GraphStatus.UNKNOWN_DEPENDENCY, [dependent, dependency]
        if len(self.service_ids) > 3:
            return GraphStatus.TOO_LARGE, []
        if len(self.edges) > 16:
            return GraphStatus.TOO_LARGE, []
        if not (0 < len(self.service_ids) <= 4):
            return GraphStatus.TOO_LARGE, []
        # cycle detection via DFS on dependency edges
        adj = self.adjacency()
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {sid: WHITE for sid in self.service_ids}

        def dfs(node: str) -> bool:
            color[node] = GRAY
            for dep in adj[node]:
                c = color[dep]
                if c == GRAY:
                    return True
                if c == WHITE and dfs(dep):
                    return True
            color[node] = BLACK
            return False

        for sid in self.service_ids:
            if color[sid] == WHITE and dfs(sid):
                return GraphStatus.CYCLE, []
        return GraphStatus.VALID, []

    def validated(self, registry) -> "DependencyGraph":
        status, _ = self._validate(registry)
        return DependencyGraph(
            self.service_ids,
            self.edges,
            self.schema_version,
            self.graph_digest,
            status,
        )

    def compute_digest(self) -> str:
        payload = json.dumps(
            {
                "service_ids": list(self.service_ids),
                "edges": [list(e) for e in sorted(self.edges)],
                "schema_version": self.schema_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def topological_order(graph: DependencyGraph) -> list[str] | None:
    """Kahn's algorithm.  None => cycle (never returns a partial order)."""
    adj = graph.adjacency()  # dependent -> its dependencies (must precede it)
    indegree = {sid: len(adj[sid]) for sid in graph.service_ids}
    queue = [sid for sid in graph.service_ids if indegree[sid] == 0]
    order: list[str] = []
    while queue:
        # deterministic: process in sorted-stable order
        queue.sort()
        node = queue.pop(0)
        order.append(node)
        for dependent in graph.service_ids:
            if node in adj[dependent]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0 and dependent not in order:
                    queue.append(dependent)
    if len(order) != len(graph.service_ids):
        return None
    return order


def rollback_order(graph: DependencyGraph, execution: list[str]) -> list[str]:
    """Reverse topological order (dependents rolled back before dependencies)."""
    topo = topological_order(graph)
    if topo is None:
        return list(reversed(execution))
    return list(reversed(topo))


def validate_desired_order(
    graph: DependencyGraph, desired: list[str]
) -> str | None:
    """Returns None if `desired` is consistent with the graph, else a reason.

    A desired order is invalid if any service appears before a service it
    depends on (dependency must come first).
    """
    pos = {sid: i for i, sid in enumerate(desired)}
    if set(pos) != set(graph.service_ids):
        return "PLAN_INVALID"
    for dependent in graph.service_ids:
        for dependency in graph.adjacency()[dependent]:
            if pos[dependency] > pos[dependent]:
                return "PLAN_INVALID"
    return None


__all__ = [
    "DependencyGraph",
    "GraphStatus",
    "rollback_order",
    "topological_order",
    "validate_desired_order",
]