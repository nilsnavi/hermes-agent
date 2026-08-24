"""Sprint 1.3.17 — risk & blast aggregation (§19).

Effective global risk = max(child risks) + coordination amplification.
Effective global blast  = max(child blast) + dependency amplification.

Hard deny: HOST / NETWORK / UNKNOWN blast (and unknown risk).  For 1.3.17
rehearsal/shadow only RESOURCE and SERVICE blast are allowed.
"""
from __future__ import annotations

from .models import MultiServiceExecutionPlan


def effective_risk(plan: MultiServiceExecutionPlan) -> str:
    order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    level = 0
    for c in plan.children:
        idx = order.index(c.risk.upper()) if c.risk.upper() in order else 3
        level = max(level, idx)
    if len(plan.service_set) > 1:
        level = min(level + 1, 3)  # coordination amplification
    return order[level]


def blast_allowed_for_plan(plan: MultiServiceExecutionPlan) -> tuple[bool, str]:
    """Only RESOURCE / SERVICE blast is allowed in 1.3.17 simulated execution."""
    for c in plan.children:
        b = str(c.blast_radius).upper()
        if b in ("HOST", "NETWORK", "UNKNOWN"):
            return False, f"forbidden-blast:{b}"
    if not plan.children:
        return False, "empty-service-set"
    return True, "blast-allowed"


def effective_blast(plan: MultiServiceExecutionPlan) -> str:
    blasts = {str(c.blast_radius).upper() for c in plan.children}
    if len(plan.service_set) > 1:
        return "MULTI_SERVICE"
    if "HOST" in blasts:
        return "HOST"
    if "NETWORK" in blasts:
        return "NETWORK"
    if "UNKNOWN" in blasts:
        return "UNKNOWN"
    if "SERVICE" in blasts:
        return "SERVICE"
    return "RESOURCE"


__all__ = ["blast_allowed_for_plan", "effective_blast", "effective_risk"]