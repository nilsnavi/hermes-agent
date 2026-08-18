"""Service graph (Sprint 1.3.3 §32-§38, §65).

Bounded graph of services / processes / configs / files / ports /
sockets / domains / certificates / containers / databases / caches /
queues / upstreams / packages with typed, provenance-bearing edges.

Trust (§33): STATIC_VERIFIED may confirm identity in scope;
RUNTIME_OBSERVED / CONFIG_OBSERVED may raise risk; INFERRED /
LEARNED may ONLY raise. INFERRED/LEARNED can never grant PASS,
reduce risk, prove absence of a dependency, or prove safety.

Health (§37): PARTIAL != HEALTHY; unknown dependencies are never
treated as absent (§35). Discovery is budgeted (§35): max files,
services, processes, depth, edges, timeouts — exhaustion →
GRAPH_PARTIAL.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .models import GraphHealth, Provenance


@dataclass(frozen=True)
class GraphNode:
    name: str
    node_type: str  # SERVICE / PROCESS / CONFIG / ... (§32)
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    edge_type: str      # OWNS / USES / READS / ... (§32)
    provenance: str     # Provenance enum value
    metadata: Dict[str, str] = field(default_factory=dict)

    @property
    def can_grant(self) -> bool:
        """Only STATIC_VERIFIED may confirm identity in its scope."""
        return self.provenance == Provenance.STATIC_VERIFIED.value


#: edge types that express dependency relationships
_DEPENDENCY_EDGES = frozenset({
    "DEPENDS_ON", "REQUIRES", "USES", "READS", "WRITES",
    "CONNECTS_TO", "PROXIES_TO", "MOUNTS", "EXPOSES",
    "USES_CERTIFICATE", "MANAGED_BY", "OWNS", "LISTENS_ON",
})


class ServiceGraph:
    """Bounded service graph with provenance and health."""

    def __init__(self, health: str = "HEALTHY",
                 graph_version: str = "g1",
                 max_nodes: int = 500, max_edges: int = 2000) -> None:
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []
        self._adjacency: Dict[str, Set[str]] = {}
        self.health = health
        self.graph_version = graph_version
        self.max_nodes = max_nodes
        self.max_edges = max_edges

    # ── nodes ──────────────────────────────────────────────────────

    def add_node(self, name: str, node_type: str = "SERVICE",
                 **metadata: str) -> bool:
        """Add a node; False when the budget is exhausted (→ PARTIAL)."""
        if name in self._nodes:
            return True
        if len(self._nodes) >= self.max_nodes:
            self._mark_partial()
            return False
        self._nodes[name] = GraphNode(name, node_type, dict(metadata))
        return True

    def has_node(self, name: str) -> bool:
        return name in self._nodes

    def node_count(self) -> int:
        return len(self._nodes)

    def node(self, name: str) -> Optional[GraphNode]:
        return self._nodes.get(name)

    def nodes(self) -> List[GraphNode]:
        return list(self._nodes.values())

    # ── edges ──────────────────────────────────────────────────────

    def add_edge(self, source: str, target: str, edge_type: str,
                 provenance: str) -> bool:
        if len(self._edges) >= self.max_edges:
            self._mark_partial()
            return False
        self._edges.append(GraphEdge(
            source, target, edge_type,
            str(provenance).upper()))
        self._adjacency.setdefault(source, set()).add(target)
        return True

    def edge_count(self) -> int:
        return len(self._edges)

    def edges_from(self, name: str) -> List[GraphEdge]:
        return [e for e in self._edges if e.source == name]

    def edges_to(self, name: str) -> List[GraphEdge]:
        return [e for e in self._edges if e.target == name]

    def edges(self) -> List[GraphEdge]:
        return list(self._edges)

    def neighbors(self, name: str) -> Set[str]:
        return set(self._adjacency.get(name, set()))

    # ── dependency queries (§35) ───────────────────────────────────

    def dependencies(self, name: str) -> List[str]:
        """Direct dependency names (any provenance)."""
        return sorted(self.neighbors(name))

    def dependency_state_known(self, name: str) -> bool:
        """False when the graph is PARTIAL/UNAVAILABLE/CORRUPT or when
        the node has no STATIC_VERIFIED dependency information."""
        if self.health not in ("HEALTHY", "STALE"):
            return False
        node = self._nodes.get(name)
        if node is None:
            return False
        return True

    def has_unknown_dependencies(self, name: str) -> bool:
        """True when any dependency edge is INFERRED/LEARNED — those
        can never prove absence (§33/§35)."""
        for e in self.edges_from(name):
            if e.provenance in (Provenance.INFERRED.value,
                                Provenance.LEARNED.value):
                return True
        return False

    def transitive_dependencies(self, name: str, max_depth: int = 5,
                                max_nodes: int = 100) -> Set[str]:
        """Cycle-safe, depth-limited transitive closure."""
        seen: Set[str] = set()
        frontier = [name]
        depth = 0
        while frontier and depth < max_depth and len(seen) < max_nodes:
            nxt: Set[str] = set()
            for f in frontier:
                for nb in self.neighbors(f):
                    if nb not in seen:
                        seen.add(nb)
                        nxt.add(nb)
            frontier = list(nxt)
            depth += 1
        return seen

    # ── health ─────────────────────────────────────────────────────

    def _mark_partial(self) -> None:
        if self.health == "HEALTHY":
            self.health = "PARTIAL"

    def mark_unavailable(self) -> None:
        self.health = "UNAVAILABLE"

    def mark_corrupt(self) -> None:
        self.health = "CORRUPT"

    # ── persistence (§36) ──────────────────────────────────────────

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": 1,
            "graph_version": self.graph_version,
            "health": self.health,
            "nodes": [
                {"name": n.name, "node_type": n.node_type,
                 "metadata": n.metadata}
                for n in self._nodes.values()
            ],
            "edges": [
                {"source": e.source, "target": e.target,
                 "edge_type": e.edge_type, "provenance": e.provenance}
                for e in self._edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "ServiceGraph":
        g = cls(health=str(data.get("health", "HEALTHY")),
                graph_version=str(data.get("graph_version", "g1")))
        for n in data.get("nodes", []):
            g.add_node(str(n["name"]), str(n["node_type"]),
                       **{k: str(v) for k, v in
                          dict(n.get("metadata", {})).items()})
        for e in data.get("edges", []):
            g.add_edge(str(e["source"]), str(e["target"]),
                       str(e["edge_type"]), str(e["provenance"]))
        return g


__all__ = [
    "GraphNode",
    "GraphEdge",
    "ServiceGraph",
    "_DEPENDENCY_EDGES",
]
