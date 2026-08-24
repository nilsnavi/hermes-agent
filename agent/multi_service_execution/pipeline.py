"""Sprint 1.3.17 — multi-service execution pipeline (§8).

Orchestrates PHASE A (final prepare) and PHASE B (simulated execution):

  revalidate -> barrier -> issue authority -> fake-adapter execute
  -> verify -> stabilize -> global simulated commit -> durable receipt

Hard invariants:
* Real execution is disabled: the mode must be shadow/rehearsal and the only
  adapter is FakeServiceAdapter.  ``live_execution_permitted`` is always False.
* Adapter SUCCEEDED alone never commits; verify + stabilize + coordinator commit
  are required.
* Exactly-once: a terminal prior on the semantic key replays with 0 adapter calls.
* Any missing gate -> 0 adapter calls.
"""
from __future__ import annotations

import secrets
import time
from collections.abc import Mapping

from .authority import ExecutionRuntime
from .barrier import BarrierVerdict, ExecutionBarrier
from .commit import GlobalCommitCoordinator
from .exceptions import ExecutionDisabled, RevalidateRequired
from .executor import BoundedMultiServiceExecutor
from .fake_adapter import FakeServiceAdapter
from .flags import live_execution_permitted, multi_exec_enabled, multi_exec_mode
from .idempotency import ExecutionIdempotencyStore
from .models import (
    ChildExecutionBinding,
    ChildExecutionState,
    ExecutionMode,
    ExecutionReceipt,
    GlobalExecutionState,
    MultiServiceExecutionPlan,
    semantic_execution_key,
    service_set_hash,
    can_transition,
)
from .receipt import ExecutionReceiptStore
from .risk import blast_allowed_for_plan, effective_blast, effective_risk
from .stabilization import stabilization_check
from .verifier import VerificationResult, VerificationState, verify_child

# Generic control verbs / raw-subprocess shapes that the bounded execution
# layer must NEVER run, even in simulation (§26 negative matrix).
_DENIED_OPS = {"stop", "start", "restart", "signal", "kill", "pkill",
               "systemctl", "systemctl-restart", "raw-subprocess",
               "shell-cmd", "os-system", "dynamic-executable",
               "caller-unit", "caller-command"}
_DENIED_TARGETS = {"gateway", "scheduler", "provider", "database", "db",
                   "network", "auth", "security", "docker", "container",
                   "ssh", "unknown", "unregistered-service"}


def _op_denied(plan) -> tuple[bool, str]:
    for c in plan.children:
        op = str(c.operation).strip().lower()
        if op in _DENIED_OPS:
            return True, f"denied-op:{op}"
        if str(c.service_id).lower() in _DENIED_TARGETS:
            return True, f"denied-target:{c.service_id}"
    return False, ""


def build_execution_plan(
    coord_plan,
    *,
    generation: int = 1,
    recovery_generation: int = 1,
    global_plan_hash: str = "",
    graph_digest: str = "",
    registry_digest: str = "",
    approval_digest: str = "",
    budget_digest: str = "",
    lockset_digest: str = "",
    execution_mode: ExecutionMode = ExecutionMode.REHEARSAL,
    created_at_monotonic: float | None = None,
    expires_at_monotonic: float | None = None,
    now_monotonic: float = 0.0,
    ttl_s: float = 3600.0,
) -> MultiServiceExecutionPlan:
    """Wrap a certified ``MultiServiceChangePlan`` into an execution plan."""
    service_set = tuple(sp.service_id for sp in coord_plan.service_set)
    children = tuple(
        ChildExecutionBinding(
            service_id=sp.service_id,
            child_tx_id=f"{coord_plan.transaction_id}+{sp.service_id}+{generation}",
            child_generation=generation,
            profile_version=sp.service_profile_version,
            identity_fingerprint=sp.identity_fingerprint,
            config_fingerprint=sp.config_fingerprint,
            graph_fingerprint=sp.dependency_digest,
            risk=sp.risk, blast_radius=str(sp.blast_radius),
            approval_id=sp.approval_reference,
            budget_reservation_id=sp.budget_reference,
            lock_nonce=sp.idempotency_key or f"nonce-{sp.service_id}",
            prepared_token_hash=sp.fingerprint(),
            operation=sp.operation,
            expected_effect=sp.required_post_health,
            rollback_strategy=sp.rollback_strategy,
            verification_contract=sp.required_post_health,
        )
        for sp in coord_plan.service_set
    )
    created = created_at_monotonic if created_at_monotonic is not None else (
        now_monotonic if now_monotonic else 0.0)
    plan = MultiServiceExecutionPlan(
        global_tx_id=coord_plan.transaction_id,
        generation=generation,
        baseline_sha=coord_plan.baseline_sha,
        service_set=service_set,
        topological_order=tuple(coord_plan.execution_order),
        global_plan_hash=global_plan_hash or coord_plan.plan_hash or coord_plan.compute_hash(),
        graph_digest=graph_digest or coord_plan.dependency_graph_digest,
        registry_digest=registry_digest or coord_plan.registry_digest,
        approval_digest=approval_digest or coord_plan.approval_binding,
        budget_digest=budget_digest or coord_plan.budget_binding,
        lockset_digest=lockset_digest or coord_plan.plan_hash,
        recovery_generation=recovery_generation,
        created_at_monotonic=created,
        expires_at_monotonic=expires_at_monotonic if expires_at_monotonic is not None else created + ttl_s,
        execution_mode=execution_mode,
        children=children,
        source_plan_hash=coord_plan.compute_hash(),
        source_plan=coord_plan,
    )
    return plan


class ExecutionPipeline:
    def __init__(
        self,
        runtime: ExecutionRuntime,
        adapter: FakeServiceAdapter,
        idem: ExecutionIdempotencyStore,
        receipts: ExecutionReceiptStore,
        *,
        barrier: ExecutionBarrier | None = None,
        commit_coord: GlobalCommitCoordinator | None = None,
        executor: BoundedMultiServiceExecutor | None = None,
        clock=lambda: time.monotonic(),
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.runtime = runtime
        self.adapter = adapter
        self.idem = idem
        self.receipts = receipts
        self.barrier = barrier or ExecutionBarrier()
        self.commit_coord = commit_coord or GlobalCommitCoordinator()
        self.executor = executor or BoundedMultiServiceExecutor()
        self.clock = clock
        self._env = env

    # -- flag gates -----------------------------------------------------------
    def _execution_allowed(self) -> tuple[bool, str]:
        if not multi_exec_enabled(self._env):
            return False, "HERMES_MULTI_SERVICE_EXECUTION_V2_ENABLED=false"
        mode = multi_exec_mode(self._env)
        emode = ExecutionMode.from_str(mode)
        if not emode.permits_simulated_execution():
            return False, f"mode={mode} does not permit simulated execution"
        if live_execution_permitted(self._env):
            return False, "live execution not permitted in sprint 1.3.17"
        return True, ""

    def execute(
        self,
        plan: MultiServiceExecutionPlan,
        *,
        child_admissions: Mapping[str, bool] | None = None,
        locks_live_owned: bool = True,
        approvals_valid: bool = True,
        budgets_reserved: bool = True,
        recovery_clean: bool = True,
        identity_ok: bool = True,
        graph_ok: bool = True,
        registry_digest_ok: bool = True,
        baseline_digest_ok: bool = True,
        kill_switch_off: bool = True,
        boundary_allow: bool = True,
        executor_contract_ok: bool = True,
        no_drift: bool = True,
        verify_children: Mapping[str, VerificationResult] | None = None,
        stabilization_kwargs: Mapping | None = None,
        scenario: Mapping[str, Mapping[str, str]] | None = None,
    ) -> dict:
        t0 = self.clock()
        allowed, reason = self._execution_allowed()
        if not allowed:
            raise ExecutionDisabled(reason)
        if plan.execution_mode not in (ExecutionMode.SHADOW, ExecutionMode.REHEARSAL):
            raise ExecutionDisabled(f"plan mode {plan.execution_mode.value} not simulated")
        if plan.expired(t0):
            raise RevalidateRequired("execution plan expired")

        sem = semantic_execution_key(plan)
        # unique per-dispatch claim owner: concurrent dispatches (even on one
        # runtime instance) are distinct claimers; exactly one wins.
        owner_attempt = f"{self.runtime.instance_id}:{secrets.token_hex(6)}"
        claim = self.idem.claim(sem, owner_attempt)
        if claim == "ALREADY_TERMINAL":
            prior = self.idem.get(sem) or {}
            r = {"global_state": GlobalExecutionState.SIMULATED_COMMITTED.value
                 if prior.get("state") == "COMMITTED_SIMULATED"
                 else "REPLAYED_TERMINAL",
                 "adapter_call_count": 0, "replayed": True,
                 "prior_state": prior.get("state"),
                 "execution_id": (prior.get("result") or {}).get("execution_id", "")}
            return r
        if claim == "CLAIMED_BY_OTHER":
            return {"global_state": GlobalExecutionState.MANUAL_REVIEW_REQUIRED.value,
                    "adapter_call_count": 0, "reason": "claimed-by-other",
                    "execution_id": ""}
        if not self.idem.set_state(sem, owner_attempt, "EXECUTING"):
            return {"global_state": GlobalExecutionState.EXECUTION_DENIED.value,
                    "adapter_call_count": 0, "reason": "cannot-mark-executing",
                    "execution_id": ""}

        # blast / risk hard-deny gate (§19): HOST/NETWORK/UNKNOWN blast is never
        # executed; 1.3.17 allows only RESOURCE/SERVICE blast in simulation.
        b_allowed, b_reason = blast_allowed_for_plan(plan)
        if not b_allowed:
            self.idem.set_state(sem, owner_attempt, "FAILED_SAFE")
            return {"global_state": GlobalExecutionState.EXECUTION_DENIED.value,
                    "adapter_call_count": 0, "reason": f"blast:{b_reason}",
                    "execution_id": ""}

        # generic-control / raw-subprocess hard deny (§26)
        denied, denied_reason = _op_denied(plan)
        if denied:
            self.idem.set_state(sem, owner_attempt, "FAILED_SAFE")
            return {"global_state": GlobalExecutionState.EXECUTION_DENIED.value,
                    "adapter_call_count": 0, "reason": denied_reason,
                    "execution_id": ""}

        # PHASE A: final prepare / barrier
        barrier_verdict: BarrierVerdict = self.barrier.evaluate(
            plan,
            children_revalidated=identity_ok and graph_ok and no_drift,
            child_admissions=child_admissions,
            locks_live_owned=locks_live_owned, approvals_valid=approvals_valid,
            budgets_reserved=budgets_reserved, graph_healthy=graph_ok,
            identities_verified=identity_ok, registry_digest_ok=registry_digest_ok,
            baseline_digest_ok=baseline_digest_ok, recovery_clean=recovery_clean,
            prepared_tokens_valid=True, kill_switch_off=kill_switch_off,
            system_boundary_allow=boundary_allow,
            executor_contract_ok=executor_contract_ok, no_drift=no_drift,
        )
        if not barrier_verdict.ready:
            self.idem.set_state(sem, owner_attempt, "FAILED_SAFE")
            return {"global_state": GlobalExecutionState.EXECUTION_DENIED.value,
                    "adapter_call_count": 0,
                    "reason": f"barrier:{barrier_verdict.blocked_by()}",
                    "execution_id": ""}

        # mint one-shot authority (runtime-owned) then run PHASE B
        authority = self.runtime._issue(
            plan,
            prepared_token_set=frozenset(plan.service_set),
            approval_set=frozenset(c.approval_id for c in plan.children),
            budget_reservations=frozenset(c.budget_reservation_id for c in plan.children),
            lock_owner_set=frozenset(plan.service_set),
            now_monotonic=t0, ttl_s=plan.expires_at_monotonic - t0 + 60.0,
        )
        res = self.executor.execute(
            self.runtime, authority, plan, self.adapter,
            scenario=scenario, now_monotonic=self.clock(),
            barrier=barrier_verdict,
            locks_live_owned=locks_live_owned, approvals_valid=approvals_valid,
            budgets_reserved=budgets_reserved, recovery_clean=recovery_clean,
            identity_ok=identity_ok, graph_ok=graph_ok, no_drift=no_drift,
            kill_switch_off=kill_switch_off, boundary_allow=boundary_allow,
            executor_contract_ok=executor_contract_ok,
            child_admissions=child_admissions,
        )
        execution_id = f"exec-{plan.global_tx_id}-{secrets.token_hex(4)}"
        if res.global_state == GlobalExecutionState.EXECUTION_UNKNOWN:
            self.idem.set_state(sem, owner_attempt, "UNKNOWN_OUTCOME",
                                result={"execution_id": execution_id})
            self.receipts.write(self._make_receipt(plan, t0, "UNKNOWN_OUTCOME",
                                                   res, execution_id))
            return {"global_state": GlobalExecutionState.EXECUTION_UNKNOWN.value,
                    "adapter_call_count": res.adapter_call_count,
                    "reason": res.reason, "execution_id": execution_id}
        if res.global_state == GlobalExecutionState.COMPENSATION_REQUIRED:
            self.idem.set_state(sem, owner_attempt, "FAILED_SAFE",
                                result={"execution_id": execution_id, "compensation_required": True})
            self.receipts.write(self._make_receipt(plan, t0, "COMPENSATION_REQUIRED",
                                                   res, execution_id, comp=True))
            return {"global_state": GlobalExecutionState.COMPENSATION_REQUIRED.value,
                    "adapter_call_count": res.adapter_call_count,
                    "reason": res.reason, "execution_id": execution_id}
        if res.global_state != GlobalExecutionState.SIMULATED_VERIFYING:
            self.idem.set_state(sem, owner_attempt, "FAILED_SAFE",
                                result={"execution_id": execution_id, "reason": res.reason})
            self.receipts.write(self._make_receipt(plan, t0, res.global_state.value,
                                                   res, execution_id))
            return {"global_state": res.global_state.value,
                    "adapter_call_count": res.adapter_call_count,
                    "reason": res.reason, "execution_id": execution_id}

        # verification of succeeded children
        vresults: dict[str, VerificationState] = {}
        for sid in plan.topological_order:
            vres = (verify_children or {}).get(
                sid, VerificationResult(VerificationState.VERIFIED, "default-ok"))
            vresults[sid] = vres.state
        if any(v != VerificationState.VERIFIED for v in vresults.values()):
            self.idem.set_state(sem, owner_attempt, "FAILED_SAFE",
                                result={"execution_id": execution_id, "verify_failed": True})
            self.receipts.write(self._make_receipt(plan, t0, "VERIFY_FAILED", res,
                                                   execution_id))
            return {"global_state": GlobalExecutionState.MANUAL_REVIEW_REQUIRED.value,
                    "adapter_call_count": res.adapter_call_count,
                    "reason": "verification-failed", "execution_id": execution_id}

        child_states: dict[str, ChildExecutionState] = {
            sid: ChildExecutionState.CHILD_VERIFIED for sid in plan.topological_order
        }
        stab = stabilization_check(plan, child_states, **dict(stabilization_kwargs or {}))
        if not stab.ready_for_commit:
            self.idem.set_state(sem, owner_attempt, "FAILED_SAFE",
                                result={"execution_id": execution_id, "stabilize": False})
            self.receipts.write(self._make_receipt(plan, t0, "MANUAL_REVIEW_REQUIRED",
                                                   res, execution_id))
            return {"global_state": GlobalExecutionState.MANUAL_REVIEW_REQUIRED.value,
                    "adapter_call_count": res.adapter_call_count,
                    "reason": f"stabilization:{stab.reason}", "execution_id": execution_id}

        skw = stabilization_kwargs or {}
        final_state = self.commit_coord.decide(
            plan, child_states, stab, runtime=self.runtime, authority=authority,
            now_monotonic=self.clock(),
            locks_valid=skw.get("locks_valid", True),
            budget_valid=skw.get("budget_valid", True),
            approval_valid=skw.get("approval_valid", approvals_valid),
            recovery_clean=recovery_clean,
            compensation_pending=False,
        )
        if final_state != GlobalExecutionState.SIMULATED_COMMITTED:
            self.idem.set_state(sem, owner_attempt, "FAILED_SAFE",
                                result={"execution_id": execution_id, "commit": False})
            self.receipts.write(self._make_receipt(plan, t0, final_state.value, res,
                                                   execution_id))
            return {"global_state": final_state.value,
                    "adapter_call_count": res.adapter_call_count,
                    "reason": "commit-gate", "execution_id": execution_id}

        self.idem.set_state(sem, owner_attempt, "COMMITTED_SIMULATED",
                            result={"execution_id": execution_id})
        self.receipts.write(self._make_receipt(plan, t0, "SIMULATED_COMMITTED", res,
                                               execution_id))
        return {"global_state": GlobalExecutionState.SIMULATED_COMMITTED.value,
                "adapter_call_count": res.adapter_call_count,
                "reason": "committed-simulated", "execution_id": execution_id}

    def _make_receipt(self, plan, t0, disposition, res, execution_id, comp=False) -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id=execution_id, global_tx_id=plan.global_tx_id,
            generation=plan.generation, plan_hash=plan.plan_hash(),
            service_set_hash=service_set_hash(plan.service_set),
            started_at_monotonic=t0, completed_at_monotonic=self.clock(),
            mode=plan.execution_mode.value,
            child_outcomes=tuple(sorted(res.child_outcomes)),
            verification_summary="verified" if disposition == "SIMULATED_COMMITTED" else "n/a",
            stabilization_summary="stabilized" if disposition == "SIMULATED_COMMITTED" else "n/a",
            compensation_required=comp, final_disposition=disposition,
            adapter_call_count=res.adapter_call_count,
        )


__all__ = ["ExecutionPipeline"]