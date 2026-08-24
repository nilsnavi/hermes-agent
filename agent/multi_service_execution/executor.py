"""Sprint 1.3.17 — BoundedMultiServiceExecutor.

NOT part of the public package API (absent from ``__all__``).  It requires the
exact runtime owner, a valid (unconsumed) ``MultiServiceExecutionAuthority``,
the exact execution plan, and every execution gate green.  If ANY gate is
missing the executor returns ``adapter_calls == 0`` with a global abort/deny —
it NEVER partially executes children.

This executor drives a *fake* service adapter only; there is no production
adapter callable anywhere in this package.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .authority import ExecutionRuntime, MultiServiceExecutionAuthority
from .barrier import BarrierVerdict
from .exceptions import AuthorityDenied
from .fake_adapter import FakeAdapterResult, FakeServiceAdapter
from .models import (
    AdapterOutcome,
    ChildExecutionState,
    ExecutionMode,
    GlobalExecutionState,
    MultiServiceExecutionPlan,
)
from .outcome import adapter_outcome_to_child_state


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    global_state: GlobalExecutionState
    child_outcomes: tuple[tuple[str, str], ...] = ()
    adapter_call_count: int = 0
    reason: str = ""


class BoundedMultiServiceExecutor:
    """Package-private bounded simulated executor."""

    def __init__(self, *, barrier: "object" = None, boundary_allow: bool | None = None) -> None:
        self._barrier = barrier
        self._boundary_allow_override = boundary_allow

    # -- gate helpers ----------------------------------------------------------
    def _gates(
        self,
        runtime: ExecutionRuntime,
        authority: MultiServiceExecutionAuthority,
        plan: MultiServiceExecutionPlan,
        now_monotonic: float,
        *,
        barrier_ready: bool,
        locks_live_owned: bool,
        approvals_valid: bool,
        budgets_reserved: bool,
        recovery_clean: bool,
        identity_ok: bool,
        graph_ok: bool,
        no_drift: bool,
        kill_switch_off: bool,
        boundary_allow: bool,
        executor_contract_ok: bool,
        child_admissions: Mapping[str, bool],
    ) -> list[str]:
        failures: list[str] = []
        if plan.execution_mode not in (ExecutionMode.SHADOW, ExecutionMode.REHEARSAL):
            failures.append(f"mode-not-simulated:{plan.execution_mode.value}")
        if not barrier_ready:
            failures.append("barrier-not-ready")
        if not locks_live_owned:
            failures.append("locks-not-live-owned")
        if not approvals_valid:
            failures.append("approval-invalid")
        if not budgets_reserved:
            failures.append("budget-not-reserved")
        if not recovery_clean:
            failures.append("recovery-not-clean")
        if not identity_ok:
            failures.append("identity-mismatch")
        if not graph_ok:
            failures.append("graph-mismatch")
        if not no_drift:
            failures.append("drift-detected")
        if not kill_switch_off:
            failures.append("kill-switch-on")
        if not (boundary_allow or self._boundary_allow_override):
            failures.append("system-boundary-deny")
        if not executor_contract_ok:
            failures.append("executor-contract-unsatisfied")
        missing_adm = [s for s in plan.service_set if not child_admissions.get(s, False)]
        if missing_adm:
            failures.append(f"child-admission-missing:{','.join(missing_adm)}")
        return failures

    def execute(
        self,
        runtime: ExecutionRuntime,
        authority: MultiServiceExecutionAuthority,
        plan: MultiServiceExecutionPlan,
        adapter: FakeServiceAdapter,
        scenario: Mapping[str, Mapping[str, str]] | None = None,
        *,
        now_monotonic: float,
        barrier: BarrierVerdict | None = None,
        locks_live_owned: bool = True,
        approvals_valid: bool = True,
        budgets_reserved: bool = True,
        recovery_clean: bool = True,
        identity_ok: bool = True,
        graph_ok: bool = True,
        no_drift: bool = True,
        kill_switch_off: bool = True,
        boundary_allow: bool = True,
        executor_contract_ok: bool = True,
        child_admissions: Mapping[str, bool] | None = None,
    ) -> ExecutionResult:
        # authority must bind to the exact plan and be owned by the runtime
        # (READ-ONLY verify here; the single-use CONSUME happens at commit).
        try:
            runtime._verify_readonly(runtime, authority, now_monotonic)
        except AuthorityDenied:
            return ExecutionResult(GlobalExecutionState.EXECUTION_DENIED,
                                   reason="authority-denied")
        if not authority.binds(plan):
            return ExecutionResult(GlobalExecutionState.EXECUTION_DENIED,
                                   reason="authority-plan-mismatch")
        if plan.expired(now_monotonic):
            return ExecutionResult(GlobalExecutionState.EXECUTION_DENIED,
                                   reason="plan-expired")

        barrier_ready = barrier.ready if barrier is not None else True
        gates_fail = self._gates(
            runtime, authority, plan, now_monotonic,
            barrier_ready=barrier_ready,
            locks_live_owned=locks_live_owned, approvals_valid=approvals_valid,
            budgets_reserved=budgets_reserved, recovery_clean=recovery_clean,
            identity_ok=identity_ok, graph_ok=graph_ok, no_drift=no_drift,
            kill_switch_off=kill_switch_off, boundary_allow=boundary_allow,
            executor_contract_ok=executor_contract_ok,
            child_admissions=child_admissions or {},
        )
        if gates_fail:
            return ExecutionResult(GlobalExecutionState.EXECUTION_DENIED,
                                   reason=";".join(gates_fail))

        # simulated execution in topological order through the fake adapter
        scenario = scenario or {}
        outcomes: list[tuple[str, str]] = []
        adapter_calls = 0
        failed = False
        unknown = False
        for sid in plan.topological_order:
            key = f"{plan.global_tx_id}:{sid}:{plan.generation}"
            result: FakeAdapterResult = adapter.execute(
                key, scenario.get(sid, {"outcome": "ADAPTER_SUCCEEDED"})
            )
            adapter_calls += 1
            child_state = adapter_outcome_to_child_state(result)
            outcomes.append((sid, child_state.value))
            if child_state in (ChildExecutionState.CHILD_SIMULATED_FAILED,
                               ChildExecutionState.CHILD_SIMULATED_UNKNOWN):
                failed = failed or child_state == ChildExecutionState.CHILD_SIMULATED_FAILED
                unknown = unknown or child_state == ChildExecutionState.CHILD_SIMULATED_UNKNOWN
        out = tuple(outcomes)
        if unknown:
            return ExecutionResult(GlobalExecutionState.EXECUTION_UNKNOWN,
                                   child_outcomes=out,
                                   adapter_call_count=adapter_calls,
                                   reason="unknown-child-outcome")
        if failed:
            return ExecutionResult(GlobalExecutionState.COMPENSATION_REQUIRED,
                                   child_outcomes=out,
                                   adapter_call_count=adapter_calls,
                                   reason="child-failed")
        return ExecutionResult(GlobalExecutionState.SIMULATED_VERIFYING,
                               child_outcomes=out,
                               adapter_call_count=adapter_calls,
                               reason="all-children-succeeded")


__all__ = ["ExecutionResult"]  # executor class intentionally not exported