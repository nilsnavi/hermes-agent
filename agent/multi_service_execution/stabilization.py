"""Sprint 1.3.17 — stabilization gate (§12).

Deterministic, side-effect free.  A global simulated commit is allowed ONLY
when every child is verified, no child is unknown/failed, no compensation is
pending, all invariants pass, locks are still valid on the runtime holder,
budget/approval bindings are valid and recovery state is clean.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .models import ChildExecutionState, GlobalExecutionState, MultiServiceExecutionPlan


@dataclass(frozen=True, slots=True)
class StabilizationResult:
    ready_for_commit: bool
    reason: str
    verified_children: tuple[str, ...] = ()


def stabilization_check(
    plan: MultiServiceExecutionPlan,
    child_states: Mapping[str, ChildExecutionState],
    *,
    locks_valid: bool = True,
    budget_valid: bool = True,
    approval_valid: bool = True,
    recovery_clean: bool = True,
    compensation_pending: bool = False,
) -> StabilizationResult:
    """Return True only if the global simulated commit is permitted."""
    children = dict(child_states)
    missing = [s for s in plan.service_set if s not in children]
    if missing:
        return StabilizationResult(False, f"missing_child_evidence:{','.join(missing)}")
    unknown = [s for s, st in children.items()
               if st in (ChildExecutionState.CHILD_SIMULATED_UNKNOWN,
                         ChildExecutionState.CHILD_SIMULATED_FAILED,
                         ChildExecutionState.CHILD_COMPENSATION_REQUIRED)]
    if unknown:
        return StabilizationResult(False, f"non_verified_child:{','.join(unknown)}")
    unverified = [s for s, st in children.items() if st != ChildExecutionState.CHILD_VERIFIED]
    if unverified:
        return StabilizationResult(False, f"child_not_verified:{','.join(unverified)}")
    if compensation_pending:
        return StabilizationResult(False, "compensation_pending")
    if not locks_valid:
        return StabilizationResult(False, "locks_invalid")
    if not budget_valid:
        return StabilizationResult(False, "budget_invalid")
    if not approval_valid:
        return StabilizationResult(False, "approval_invalid")
    if not recovery_clean:
        return StabilizationResult(False, "recovery_not_clean")
    verified = tuple(sorted(children.keys()))
    return StabilizationResult(True, "stabilized", verified_children=verified)


__all__ = ["StabilizationResult", "stabilization_check"]