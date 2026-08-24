"""Sprint 1.3.17 — recovery bridge (§22).

Integrates the certified recovery classification.  If durable evidence shows an
UNKNOWN recovery outcome (or any recovery state that must not be resumed), the
execution pipeline is BLOCKED before any adapter call.  A second runtime that
re-encounters an UNKNOWN must not invoke the adapter.
"""
from __future__ import annotations

from collections.abc import Mapping

from .models import MultiServiceExecutionPlan

# Recovery dispositions that must NEVER be resumed into execution.
_BLOCKED_RECOVERY = {"UNKNOWN_RECOVERY_STATE", "MANUAL_REVIEW_REQUIRED"}


def recovery_allows_execution(
    plan: MultiServiceExecutionPlan,
    recovery_state: Mapping[str, object] | None = None,
) -> tuple[bool, str]:
    """Return (allowed, reason).  Fail closed on missing / unknown recovery."""
    recovery_state = recovery_state or {}
    disposition = recovery_state.get("classification")
    if disposition is None:
        # no durable recovery evidence yet -> not allowed to run blind
        return False, "no-recovery-evidence"
    if disposition in _BLOCKED_RECOVERY:
        return False, f"recovery-{disposition}"
    if disposition == "TERMINAL_RECOVERY":
        return False, "recovery-terminal"
    return True, "recovery-clean"


def recovery_requires_manual(plan: MultiServiceExecutionPlan,
                             recovery_state: Mapping[str, object] | None) -> bool:
    allowed, _ = recovery_allows_execution(plan, recovery_state)
    return not allowed


__all__ = ["recovery_allows_execution", "recovery_requires_manual"]