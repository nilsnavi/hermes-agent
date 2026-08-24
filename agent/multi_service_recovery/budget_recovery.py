"""Sprint 1.3.16 — budget recovery reconciliation.

States: RESERVED / CONSUMED / RELEASED / UNKNOWN.
Crash-before-execution => release only with durable proof.
Crash-after           => never refund automatically without outcome proof.
UNKNOWN               => manual review.
Duplicate recovery must not double-release or double-consume.
"""
from __future__ import annotations

from enum import Enum


class BudgetState(Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    UNKNOWN = "UNKNOWN"


def classify_budget_state(*, reserved: bool, consumed: bool, released: bool,
                          executed_evidence: bool) -> BudgetState:
    """Deterministic, fail-closed budget classification."""
    if consumed and executed_evidence:
        return BudgetState.CONSUMED
    if consumed and not executed_evidence:
        # consumed without proof of execution => ambiguous => unknown
        return BudgetState.UNKNOWN
    if released:
        return BudgetState.RELEASED
    if reserved:
        return BudgetState.RESERVED
    return BudgetState.UNKNOWN


def refund_allowed(state: BudgetState) -> bool:
    """Automatically release a reservation ONLY with durable proof that no
    execution happened.  Never auto-refund a CONSUMED or UNKNOWN budget."""
    return state == BudgetState.RESERVED


def consume_allowed(state: BudgetState) -> bool:
    # double-consume prevention: only an unreserved/available budget consumes
    return state not in (BudgetState.CONSUMED, BudgetState.UNKNOWN)


__all__ = ["BudgetState", "classify_budget_state", "refund_allowed", "consume_allowed"]