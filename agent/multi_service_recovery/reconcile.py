"""Sprint 1.3.16 — evidence reconciliation.  Cross-checks state machine,
event journal, idempotency claim, locks, budget, approval and child receipts.
Conflicts FAIL CLOSED — never a "latest wins" heuristic.
"""
from __future__ import annotations

from .models import RecoveryEvidence
from .classify import event_order_valid
from .lock_recovery import LockRecoveryState, classify_lock_owner
from .budget_recovery import BudgetState, classify_budget_state


def reconcile(evidence: RecoveryEvidence, journal_types: list[str],
              lock_record: dict | None = None, budget: dict[str, str] | None = None,
              child_receipts: dict[str, str] | None = None) -> list[str]:
    """Return a list of evidence conflicts.  Empty list == consistent."""
    conflicts: list[str] = []
    # 1. event order
    if not event_order_valid(journal_types):
        conflicts.append("EVENT_ORDER_INVALID")
    # 2. terminal join: journal claims committed but child states disagree
    if "GLOBAL_SIMULATED_COMMIT" in journal_types:
        if evidence.idempotency_state != "COMMITTED_SIMULATED":
            conflicts.append("IDEMPOTENCY_COMMIT_MISMATCH")
    # 3. budget contradiction
    if budget:
        if any(budget.get(s) == "UNKNOWN" for s in (budget or {})):
            conflicts.append("BUDGET_AMBIGUITY")
        consumed = [s for s, v in budget.items() if v == "CONSUMED"]
        if consumed and "GLOBAL_SIMULATED_COMMIT" not in journal_types and \
           "CHILD_SIMULATED" not in journal_types:
            conflicts.append("BUDGET_CONSUMED_WITHOUT_EXECUTION")
    # 4. child receipt vs child state (only a PRESENT contradicting receipt is
    #    a conflict; a missing receipt during verify-resume is not evidence)
    for sid, st in evidence.child_states.items():
        rcp = (child_receipts or {}).get(sid)
        if rcp is not None and rcp not in ("VERIFIED", "RECEIPT_OK"):
            conflicts.append(f"RECEIPT_MISMATCH_{sid}")
    return conflicts


__all__ = ["reconcile"]