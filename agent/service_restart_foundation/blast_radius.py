"""Sprint 1.3.12 — blast radius computation.

Future autonomous restart requires blast radius <= SERVICE. Any cascade risk
(dependents / bound units) escalates to MULTI_SERVICE.
"""
from __future__ import annotations

from enum import Enum
from collections.abc import Sequence


class BlastVerdict(Enum):
    SERVICE = "SERVICE"
    MULTI_SERVICE = "MULTI_SERVICE"


def compute_blast_radius(
    static_ceiling: str,
    critical_dependents: Sequence = (),
    active_dependents: Sequence = (),
    bound_units: Sequence = (),
    shared_resources: Sequence = (),
) -> str:
    """Compute effective blast radius from the static ceiling plus live cascade."""
    if static_ceiling == "MULTI_SERVICE":
        return "MULTI_SERVICE"
    if critical_dependents or active_dependents or bound_units or shared_resources:
        return "MULTI_SERVICE"
    return BlastVerdict.SERVICE.value


def blast_acceptable(blast: str) -> bool:
    """Future autonomous restart in 1.3.12 requires blast radius <= SERVICE."""
    return blast == BlastVerdict.SERVICE.value


__all__ = ["BlastVerdict", "blast_acceptable", "compute_blast_radius"]