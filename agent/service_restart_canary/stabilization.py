"""Sprint 1.3.13 — single aux service restart canary (stabilization health).

Bounded health window: T+0, T+2, T+5, T+10. All critical checks must be
HEALTHY; any DEGRADED/UNKNOWN/UNHEALTHY -> no COMMIT.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HealthSample:
    offset: float
    status: str  # HEALTHY | DEGRADED | UNKNOWN | UNHEALTHY


STABILIZATION_OFFSETS = (0.0, 2.0, 5.0, 10.0)


def evaluate_stabilization(samples: list[HealthSample]) -> tuple[bool, str]:
    """All mandated offsets present + all HEALTHY -> stable."""
    present = {round(s.offset, 1) for s in samples}
    required = {round(o, 1) for o in STABILIZATION_OFFSETS}
    if not required.issubset(present):
        return False, "incomplete_window"
    if any(s.status != "HEALTHY" for s in samples):
        bad = [s.status for s in samples if s.status != "HEALTHY"]
        return False, f"not_healthy:{bad[0]}"
    return True, "stabilized"


def sample(offset: float, status: str) -> HealthSample:
    return HealthSample(offset=offset, status=status)


__all__ = [
    "STABILIZATION_OFFSETS",
    "HealthSample",
    "evaluate_stabilization",
    "sample",
]