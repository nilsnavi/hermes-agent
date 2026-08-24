"""Sprint 1.3.15 — health contracts (pre/post) for each child.

A health contract binds the pre-observation that made the transaction safe to
schedule and the required post-observation.  Degraded pre-health or a missing
post-health contract disqualifies the child (and therefore the whole plan).
"""
from __future__ import annotations


def pre_health_green(pre_health: str) -> bool:
    return pre_health == "GREEN"


def post_health_acceptable(required: str, observed: str) -> bool:
    """Required post-health may be satisfied by an equal-or-better state."""
    rank = {"RED": 0, "YELLOW": 1, "GREEN": 2}
    return rank.get(observed, 0) >= rank.get(required, 0)


__all__ = ["post_health_acceptable", "pre_health_green"]