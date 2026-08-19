"""Sprint 1.3.12 — dependency quiescence (restart is not safe by service alone).

Named/critical dependents, active dependents, shared resources and bound units
are checked. Cascade risk -> DENY / blast MULTI_SERVICE.
"""
from __future__ import annotations

from enum import Enum
from collections.abc import Sequence


class DependencyVerdict(Enum):
    SAFE = "SAFE"
    RAISE_RISK = "RAISE_RISK"
    DENY = "DENY"


def evaluate_dependencies(
    critical_dependents: Sequence = (),
    active_dependents: Sequence = (),
    shared_resources: Sequence = (),
    bound_units: Sequence = (),
    requires: Sequence = (),
    wants: Sequence = (),
    binds_to: Sequence = (),
    part_of: Sequence = (),
) -> "DependencyCheck":
    """Return a DependencyCheck carrying the verdict and a safe flag."""
    if critical_dependents or active_dependents:
        verdict = DependencyVerdict.DENY
    elif bound_units or binds_to or part_of:
        verdict = DependencyVerdict.DENY
    elif shared_resources:
        verdict = DependencyVerdict.RAISE_RISK
    elif requires or wants:
        # declared deps without live dependents are informational but raise risk
        verdict = DependencyVerdict.RAISE_RISK
    else:
        verdict = DependencyVerdict.SAFE
    return DependencyCheck(
        verdict=verdict,
        critical_dependents=tuple(critical_dependents),
        active_dependents=tuple(active_dependents),
        bound_units=tuple(bound_units),
        shared_resources=tuple(shared_resources),
    )


class DependencyCheck:
    __slots__ = (
        "verdict",
        "critical_dependents",
        "active_dependents",
        "bound_units",
        "shared_resources",
    )

    def __init__(self, verdict, critical_dependents=(),
                 active_dependents=(), bound_units=(), shared_resources=()) -> None:
        self.verdict = verdict
        self.critical_dependents = critical_dependents
        self.active_dependents = active_dependents
        self.bound_units = bound_units
        self.shared_resources = shared_resources


__all__ = ["DependencyCheck", "DependencyVerdict", "evaluate_dependencies"]