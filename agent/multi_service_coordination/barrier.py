"""Sprint 1.3.15 — prepare barrier.

All children must reach READY before the parent advances past BARRIER_READY.
If even one child is INVALID / EXPIRED / DRIFTED / FAILED the whole
transaction aborts (abort-condition propagates up as BARRIER_FAILED).
"""
from __future__ import annotations

from .models import PrepareBarrier

ABORT_STATES = {"INVALID", "EXPIRED", "DRIFTED", "FAILED", "INCOMPLETE"}


def evaluate_barrier(barrier: PrepareBarrier) -> str:
    """Returns READY if all children are READY, else the worst abort state."""
    for sid in barrier.required_services:
        state = barrier.service_states.get(sid, "INCOMPLETE")
        if state == "READY":
            continue
        if state in ABORT_STATES:
            return state
        # anything other than READY and not an explicit abort => INCOMPLETE
        return "INCOMPLETE"
    return "READY"


__all__ = ["ABORT_STATES", "evaluate_barrier"]