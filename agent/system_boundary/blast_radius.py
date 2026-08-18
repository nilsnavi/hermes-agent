"""Blast radius (Sprint 1.3.3 §39-§41).

Canonical: NONE / LOCAL / SERVICE / MULTI_SERVICE / HOST / NETWORK /
UNKNOWN. UNKNOWN != NONE. Traversal is cycle-safe, depth-limited and
budgeted. The SBL may only RAISE risk via the radius floor.
"""

from typing import Dict, Optional

from .models import BlastRadius, Provenance
from .service_graph import ServiceGraph

BLAST_RADIUS_VALUES: Dict[str, int] = {
    BlastRadius.NONE.value: 0,
    BlastRadius.LOCAL.value: 1,
    BlastRadius.SERVICE.value: 2,
    BlastRadius.MULTI_SERVICE.value: 3,
    BlastRadius.HOST.value: 4,
    BlastRadius.NETWORK.value: 5,
    BlastRadius.UNKNOWN.value: 100,  # unknown != none
}

_RADIUS_RISK_FLOOR = {
    BlastRadius.NONE.value: "NONE",
    BlastRadius.LOCAL.value: "READ_ONLY",
    BlastRadius.SERVICE.value: "SYSTEM",
    BlastRadius.MULTI_SERVICE.value: "SYSTEM",
    BlastRadius.HOST.value: "SYSTEM",
    BlastRadius.NETWORK.value: "CRITICAL",
    BlastRadius.UNKNOWN.value: "CRITICAL",
}


def blast_radius_for_target(
    target: str,
    graph: Optional[ServiceGraph],
    max_depth: int = 4,
    max_nodes: int = 100,
) -> str:
    """Compute the blast radius of a mutation targeting ``target``.

    Conservative: a missing/unavailable graph or any INFERRED/LEARNED
    dependency raises the radius — never proves safety (§33/§35).
    """
    if graph is None or graph.health in ("UNAVAILABLE", "CORRUPT"):
        return BlastRadius.UNKNOWN.value
    if not graph.has_node(target):
        return BlastRadius.LOCAL.value

    deps = graph.transitive_dependencies(target, max_depth, max_nodes)
    if not deps and graph.has_unknown_dependencies(target):
        # unknown dependency set != empty
        return BlastRadius.UNKNOWN.value

    count = len(deps)
    if graph.has_unknown_dependencies(target):
        return BlastRadius.MULTI_SERVICE.value
    if count >= 3:
        return BlastRadius.MULTI_SERVICE.value
    if count >= 1:
        return BlastRadius.SERVICE.value
    return BlastRadius.LOCAL.value


def risk_floor_for_radius(radius: str) -> str:
    """§41 — radius → risk floor (SBL may only raise)."""
    return _RADIUS_RISK_FLOOR.get(
        str(radius).upper(), BlastRadius.UNKNOWN.value
    ) if str(radius).upper() in _RADIUS_RISK_FLOOR else \
        _RADIUS_RISK_FLOOR[BlastRadius.UNKNOWN.value]


def is_high_radius(radius: str) -> bool:
    return BLAST_RADIUS_VALUES.get(
        str(radius).upper(), 100) >= BLAST_RADIUS_VALUES[
            BlastRadius.MULTI_SERVICE.value]


__all__ = [
    "BLAST_RADIUS_VALUES",
    "blast_radius_for_target",
    "risk_floor_for_radius",
    "is_high_radius",
]
