"""Sprint 1.3.17 — GlobalCommitCoordinator (§12 / §13).

The coordinator, not any child adapter, owns the global simulated commit.
A child adapter success NEVER commits globally.  Global simulated commit is
emitted only when EVERY child is verified, no child is unknown/failed, no
compensation is pending, all invariants pass, locks are still valid, budget /
approval bindings are valid and recovery state is clean.  Otherwise:
NO GLOBAL SUCCESS.
"""
from __future__ import annotations

from collections.abc import Mapping

from .authority import ExecutionRuntime
from .models import (
    ChildExecutionState,
    ExecutionMode,
    GlobalExecutionState,
    MultiServiceExecutionPlan,
    can_transition,
)
from .stabilization import StabilizationResult


class GlobalCommitCoordinator:
    """Owner-only global simulated commit gate."""

    def decide(
        self,
        plan: MultiServiceExecutionPlan,
        child_states: Mapping[str, ChildExecutionState],
        stabilization: StabilizationResult,
        *,
        runtime: ExecutionRuntime,
        authority=None,
        now_monotonic: float,
        locks_valid: bool = True,
        budget_valid: bool = True,
        approval_valid: bool = True,
        recovery_clean: bool = True,
        compensation_pending: bool = False,
    ) -> GlobalExecutionState:
        if not stabilization.ready_for_commit:
            return GlobalExecutionState.MANUAL_REVIEW_REQUIRED
        if any(st != ChildExecutionState.CHILD_VERIFIED for st in child_states.values()):
            return GlobalExecutionState.MANUAL_REVIEW_REQUIRED
        missing = [s for s in plan.service_set if s not in child_states]
        if missing:
            return GlobalExecutionState.EXECUTION_ABORTED
        if compensation_pending:
            return GlobalExecutionState.COMPENSATION_REQUIRED
        if not locks_valid:
            return GlobalExecutionState.EXECUTION_ABORTED
        if not budget_valid:
            return GlobalExecutionState.MANUAL_REVIEW_REQUIRED
        if not approval_valid:
            return GlobalExecutionState.MANUAL_REVIEW_REQUIRED
        if not recovery_clean:
            return GlobalExecutionState.MANUAL_REVIEW_REQUIRED
        # coordinator-ownership proof: the authority must still be valid and
        # bound to the same runtime.  Commit consumes the single-use authority
        # exactly once (one-shot, non-replayable).
        if authority is not None:
            try:
                runtime._verify_and_consume(runtime, authority, now_monotonic)
            except Exception:
                return GlobalExecutionState.EXECUTION_DENIED
        if not can_transition(GlobalExecutionState.SIMULATED_COMMIT_READY,
                              GlobalExecutionState.SIMULATED_COMMITTED):
            return GlobalExecutionState.MANUAL_REVIEW_REQUIRED
        return GlobalExecutionState.SIMULATED_COMMITTED


__all__ = ["GlobalCommitCoordinator"]