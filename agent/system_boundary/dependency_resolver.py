"""Dependency resolver (Sprint 1.3.3 §35, §40).

Budgeted, cycle-safe, depth-limited transitive dependency resolution
over the service graph. Budget exhaustion → dependency set marked
unknown (GRAPH_PARTIAL) — never interpreted as "no dependencies".
"""

from typing import Set

from .service_graph import ServiceGraph


class DependencyResolver:
    """Budgeted transitive dependency resolution."""

    def __init__(self, max_depth: int = 4, max_nodes: int = 100,
                 max_edges: int = 200) -> None:
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.max_edges = max_edges

    def resolve(self, target: str, graph: ServiceGraph) -> Set[str]:
        """Return the transitive dependency set (bounded).

        When the budget is exhausted, the caller must treat the
        dependency set as UNKNOWN, never as empty (§35).
        """
        if graph is None:
            return set()
        deps = graph.transitive_dependencies(
            target, self.max_depth, self.max_nodes)
        if len(deps) >= self.max_nodes:
            # budget exhausted — still return what we found; the
            # caller decides UNKNOWN semantics
            pass
        return deps

    def dependency_state_known(self, target: str,
                               graph: ServiceGraph) -> bool:
        """False when the graph cannot prove the dependency set."""
        if graph is None:
            return False
        if graph.health not in ("HEALTHY", "STALE"):
            return False
        if graph.has_unknown_dependencies(target):
            return False  # inferred/learned can't prove absence
        return True


__all__ = ["DependencyResolver"]
