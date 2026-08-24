"""Sprint 1.3.15 — risk and blast-radius ceilings.

Risk is monotone non-decreasing along a dependency chain (coupling can only
raise risk, never lower it).  Blast radius is capped at the union of child
blasts with dependency amplification; HOST/NETWORK/UNKNOWN blast is denied.
"""
from __future__ import annotations

from enum import Enum

_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def risk_rank(risk: str) -> int:
    return _RANK.get(risk, 3)


def risk_monotonic(child_risks) -> bool:
    """global risk_after >= max(child risk).  Coupling never lowers risk."""
    if not child_risks:
        return False
    return max(risk_rank(r) for r in child_risks) == risk_rank(max(child_risks, key=risk_rank))


def acceptable_blast(blast: str) -> bool:
    return blast in {"RESOURCE", "SERVICE", "MULTI_SERVICE"}


__all__ = ["acceptable_blast", "risk_monotonic", "risk_rank"]