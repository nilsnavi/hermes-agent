"""Sprint 1.3.15 — MultiServiceCoordinator (sole authority orchestrator).

Drives the bounded global state machine for a shadow/rehearsal coordination.

    CREATED -> PLANNED -> ELIGIBILITY_CHECKED -> LOCKS_ACQUIRED -> PREPARED
    -> BARRIER_READY -> EXECUTION_READY -> SIMULATED_EXECUTING -> VERIFYING
    -> COMMIT_READY -> COMMITTED_SIMULATED

Failure corridor: DENIED / PREPARE_FAILED / LOCK_FAILED / BARRIER_FAILED /
CHILD_FAILED / VERIFY_FAILED / COMPENSATION_REQUIRED / COMPENSATION_FAILED /
UNKNOWN_OUTCOME / MANUAL_REVIEW_REQUIRED.

There is NO real EXECUTING state and NO real adapter call: even after every
gate is green, execution_guard returns MULTI_SERVICE_EXECUTION_DISABLED and
adapter_calls stays 0.

Flow: global idempotency claim FIRST -> canonical locks -> duplicate recheck
-> child approvals -> child budgets -> child prepare -> barrier -> simulation
-> verify -> simulated commit.
"""
from __future__ import annotations

import secrets
import time
from collections.abc import Mapping

from . import events as ev
from ._durable import CoordinationStore
from .approval import ApprovalBinder
from .budget import CoordinationBudget
from .compensation import compensation_required_strategy
from .eligibility import aggregate_eligibility
from .exceptions import CoordinatorStateError
from .execution_guard import MULTI_SERVICE_EXECUTION_DISABLED, execution_disabled
from .idempotency import semantic_key
from .lock_order import CanonicalLockSet
from .models import (
    CoordinatorState,
    GlobalOutcome,
    GlobalTransaction,
    MultiServiceChangePlan,
    MultiServiceExecutionPermit,
    PrepareBarrier,
    ServiceTransaction,
    check_transition,
    TERMINAL_STATES,
)
from .registry import CoordinationRegistry
from .telemetry import CoordinatorTelemetry


class _GateContext:
    """Injectables for a single shadow evaluation.  Never wired to real tooling."""

    def __init__(
        self,
        child_eligibility: Mapping[str, object],
        prepare_gates: Mapping[str, Mapping] | None = None,
        sim_outcome: Mapping[str, bool] | None = None,
        verify_ok: bool = True,
    ) -> None:
        self.child_eligibility = dict(child_eligibility)
        self.prepare_gates = prepare_gates or {}
        self.sim_outcome = sim_outcome or {}
        self.verify_ok = verify_ok


class MultiServiceCoordinator:
    def __init__(
        self,
        store: CoordinationStore,
        registry: CoordinationRegistry,
        *,
        budget: CoordinationBudget | None = None,
        telemetry: CoordinatorTelemetry | None = None,
        lock_set: CanonicalLockSet | None = None,
        clock=lambda: time.time(),
    ) -> None:
        self.store = store
        self.registry = registry
        self.budget = budget or CoordinationBudget(store.root / "budgets")
        self.telemetry = telemetry or CoordinatorTelemetry(store.root / "telemetry")
        self.lock_set = lock_set or CanonicalLockSet()
        self.clock = clock
        self.approvals = ApprovalBinder(store, clock=clock)

    def _transition(
        self, tx: GlobalTransaction, new: CoordinatorState, reason: str | None = None
    ) -> None:
        old = tx.state
        if old == new:
            # no-op: keep the reached state, just attach reason + persist
            if reason:
                tx.denial_reason = reason
            self.store.transition_global(tx.transaction_id, new.value, reason=reason)
            return
        if not check_transition(old, new):
            if old in TERMINAL_STATES:
                raise CoordinatorStateError(f"{old.value} is terminal")
            raise CoordinatorStateError(f"no edge {old.value} -> {new.value}")
        tx.state = new
        if reason:
            tx.denial_reason = reason
        self.store.transition_global(tx.transaction_id, new.value, reason=reason)

    def _fail(
        self,
        tx: GlobalTransaction,
        sem: str,
        agg,
        reason: str,
        outcomes: Mapping[str, object] | None = None,
    ) -> GlobalTransaction:
        self.telemetry.plans_denied() if reason == "CHILD_DENIED" else None
        self._transition(tx, CoordinatorState.DENIED, reason)
        tx.outcome = GlobalOutcome.DENIED
        self.store.record_result(sem, tx.transaction_id, "DENIED", dict(outcomes) if outcomes else {})
        reason_key = (
            "CHILD_DENIED"
            if agg is not None and getattr(agg, "denied_children", ())
            else "REVALIDATE_REQUIRED"
        )
        self.store.journal.append(ev.GLOBAL_FAILED, {"reason": reason_key or reason})
        self.lock_set.release_many(
            tx.transaction_id, [s.service_id for s in tx.children]
        )
        return tx

    def coordinate(
        self, plan: MultiServiceChangePlan, gctx: _GateContext
    ) -> GlobalTransaction:
        tx = GlobalTransaction(
            plan=plan,
            transaction_id=plan.transaction_id,
            state=CoordinatorState.CREATED,
            children=[
                ServiceTransaction(plan.transaction_id, sp.service_id, 1)
                for sp in plan.service_set
            ],
        )
        self._transition(tx, CoordinatorState.PLANNED)

        sem = semantic_key(plan, plan.registry_digest or self.registry.registry_digest)
        self.telemetry.plans_total()

        # 1. global idempotency claim FIRST
        claim = self.store.claim_global(sem, tx.transaction_id)
        if claim in {"ALREADY_TERMINAL", "CLAIMED_BY_OTHER"}:
            self.telemetry.duplicate_global_intents()
            prior = self.store.get_idem(sem) or {}
            if prior.get("result"):
                tx.state = CoordinatorState.COMMITTED_SIMULATED
                tx.outcome = GlobalOutcome.COMMITTED_SIMULATED
            else:
                tx.state = CoordinatorState.MANUAL_REVIEW_REQUIRED
                tx.outcome = GlobalOutcome.MANUAL_REVIEW_REQUIRED
            return tx
        if claim != "CLAIMED_BY_ME":
            tx.state = CoordinatorState.MANUAL_REVIEW_REQUIRED
            tx.outcome = GlobalOutcome.MANUAL_REVIEW_REQUIRED
            return tx
        self.store.journal.append(ev.GLOBAL_CLAIMED, {"transaction_id": tx.transaction_id})

        # 2. eligibility (all-or-nothing)
        self._transition(tx, CoordinatorState.ELIGIBILITY_CHECKED)
        agg = aggregate_eligibility(gctx.child_eligibility)
        if not agg.allowed:
            return self._fail(
                tx, sem, agg,
                "CHILD_DENIED" if agg.denied_children else "REVALIDATE_REQUIRED",
                {"denied": list(agg.denied_children), "unknown": list(agg.unknown_children)},
            )

        # 3. canonical locks (deadlock-free, never caller order)
        sids = [sp.service_id for sp in plan.service_set]
        acquired = self.lock_set.acquire_many(tx.transaction_id, sids)
        if acquired is None:
            self.telemetry.lock_failures()
            self._transition(tx, CoordinatorState.LOCK_FAILED, "LOCK_CONFLICT")
            tx.outcome = GlobalOutcome.DENIED
            self.store.record_result(sem, tx.transaction_id, "LOCK_FAILED")
            self.store.journal.append(ev.GLOBAL_FAILED, {"reason": "LOCK_CONFLICT"})
            return tx
        self.store.journal.append(ev.LOCK_ACQUIRED, {"order": list(acquired)})
        self._transition(tx, CoordinatorState.LOCKS_ACQUIRED)

        # 4. child global approval validation (multi-service approval does NOT
        #    replace child approvals — each child is validated separately).
        for sp in plan.service_set:
            if not sp.approval_reference:
                self._transition(tx, CoordinatorState.DENIED, "APPROVAL_MISSING")
                tx.outcome = GlobalOutcome.DENIED
                self.store.record_result(sem, tx.transaction_id, "DENIED")
                self.lock_set.release_many(tx.transaction_id, sids)
                return tx
            verdict = self.approvals.validate_binding(
                sp.approval_reference, _approval_expected(plan)
            )
            if verdict != "APPROVED":
                self._transition(tx, CoordinatorState.DENIED, verdict)
                tx.outcome = GlobalOutcome.DENIED
                self.store.record_result(sem, tx.transaction_id, "DENIED")
                self.lock_set.release_many(tx.transaction_id, sids)
                return tx

        # 5. prepare phase (all-or-nothing) + prepare barrier
        self._transition(tx, CoordinatorState.PREPARED)
        barrier = PrepareBarrier(tx.transaction_id, tuple(sids))
        failed_prepare = None
        for sp in plan.service_set:
            gates = dict(gctx.prepare_gates.get(sp.service_id, {}))
            if not _prepare_ok(gates):
                barrier.mark(sp.service_id, "FAILED")
                failed_prepare = gates.get("_fail_reason", "PREPARE_STEP_FAILED")
                break
            barrier.mark(sp.service_id, "READY")
            self.store.journal.append(ev.CHILD_PREPARED, {"service_id": sp.service_id})
        self._transition(tx, CoordinatorState.BARRIER_READY)
        if failed_prepare or not barrier.all_ready:
            self.telemetry.prepare_failures()
            self._transition(tx, CoordinatorState.COMPENSATION_REQUIRED, failed_prepare)
            tx.outcome = GlobalOutcome.COMPENSATION_REQUIRED
            self.store.record_result(sem, tx.transaction_id, "COMPENSATION_REQUIRED")
            self.store.journal.append(ev.COMPENSATION_REQUIRED, {"reason": failed_prepare})
            self.lock_set.release_many(tx.transaction_id, sids)
            return tx
        self.store.journal.append(ev.BARRIER_READY, {})
        self._transition(tx, CoordinatorState.EXECUTION_READY)

        # 6. simulation ONLY — P0 execution guard always disabled
        self._transition(tx, CoordinatorState.SIMULATED_EXECUTING)
        self.store.journal.append(ev.SIMULATION_STARTED, {})
        permit = MultiServiceExecutionPermit(
            permit_id=f"permit-{secrets.token_hex(8)}",
            global_tx_id=tx.transaction_id,
            plan_hash=plan.plan_hash,
            registry_digest=plan.registry_digest or self.registry.registry_digest,
            execution_order=plan.execution_order,
            rollback_order=plan.rollback_order,
            issued_at=self.clock(),
            expires_at=self.clock() + 5.0,
        )
        guard = execution_disabled(permit)
        assert guard == MULTI_SERVICE_EXECUTION_DISABLED

        # duplicate recheck AFTER locks + approvals + budgets (TOCTOU close)
        rec = self.store.get_idem(sem)
        if rec and rec.get("state") in {"COMMITTED_SIMULATED", "DENIED", "COMPENSATION_FAILED"}:
            if rec.get("owner_id") != tx.transaction_id:
                self.telemetry.duplicate_global_intents()
                self.lock_set.release_many(tx.transaction_id, sids)
                if rec.get("result"):
                    tx.state = CoordinatorState.COMMITTED_SIMULATED
                    tx.outcome = GlobalOutcome.COMMITTED_SIMULATED
                else:
                    tx.state = CoordinatorState.MANUAL_REVIEW_REQUIRED
                    tx.outcome = GlobalOutcome.MANUAL_REVIEW_REQUIRED
                return tx

        # simulate each child (NO real adapter)
        child_outcomes: dict[str, str] = {}
        for sid in plan.execution_order:
            child = tx.child(sid)
            sim = gctx.sim_outcome.get(sid, True)
            outcome = "SUCCESS" if sim is True else ("FAILED" if sim is False else "UNKNOWN")
            child_outcomes[sid] = outcome
            if child is not None:
                child.simulated_success = sim is True
                child.state = f"SIMULATED_{outcome}"
            self.store.journal.append(
                ev.CHILD_SIMULATED, {"service_id": sid, "ok": sim is True}
            )

        # 7. verify
        self._transition(tx, CoordinatorState.VERIFYING)
        if not gctx.verify_ok:
            self._transition(tx, CoordinatorState.VERIFY_FAILED)
            return self._partial_failure(tx, sem, sids, child_outcomes, "VERIFY_FAILED")

        # 8. partial failure classification (never PARTIAL_COMMIT_SUCCESS)
        if any(v == "FAILED" for v in child_outcomes.values()):
            return self._partial_failure(tx, sem, sids, child_outcomes, "CHILD_FAILED")
        if any(v == "UNKNOWN" for v in child_outcomes.values()):
            self.telemetry.unknown_outcomes()
            self._transition(tx, CoordinatorState.UNKNOWN_OUTCOME)
            tx.outcome = GlobalOutcome.UNKNOWN_OUTCOME
            self.store.record_result(sem, tx.transaction_id, "UNKNOWN_OUTCOME")
            self.store.journal.append(ev.GLOBAL_FAILED, {"reason": "UNKNOWN_OUTCOME"})
            self.lock_set.release_many(tx.transaction_id, sids)
            return tx
        self.store.journal.append(ev.VERIFY_COMPLETED, {})

        # 9. simulated commit
        self._transition(tx, CoordinatorState.COMMIT_READY)
        self._transition(tx, CoordinatorState.COMMITTED_SIMULATED)
        tx.outcome = GlobalOutcome.COMMITTED_SIMULATED
        self.telemetry.simulated_commits()
        self.store.record_result(
            sem, tx.transaction_id, "COMMITTED_SIMULATED",
            {"order": list(plan.execution_order)},
        )
        self.store.journal.append(
            ev.GLOBAL_SIMULATED_COMMIT, {"transaction_id": tx.transaction_id}
        )
        self.lock_set.release_many(tx.transaction_id, sids)
        return tx

    def _partial_failure(self, tx, sem, sids, outcomes, reason) -> GlobalTransaction:
        self.telemetry.compensation_required()
        # Reason is already a terminal failure state (e.g. VERIFY_FAILED) -> do
        # NOT re-transition (terminal states have no outgoing edges).  Only
        # transition when we are still in a non-terminal state.
        target = CoordinatorState.COMPENSATION_REQUIRED
        if not check_transition(tx.state, target):
            target = tx.state  # keep the reached terminal failure state
        self._transition(tx, target, reason)
        tx.outcome = GlobalOutcome.COMPENSATION_REQUIRED
        comp = compensation_required_strategy(tx.plan, outcomes)
        if not comp.rollback_supported:
            tx.state = CoordinatorState.COMPENSATION_FAILED
            tx.outcome = GlobalOutcome.COMPENSATION_FAILED
        self.store.record_result(
            sem, tx.transaction_id, tx.state.value, {"outcomes": outcomes}
        )
        self.store.journal.append(
            ev.COMPENSATION_REQUIRED, {"reason": reason, "outcomes": outcomes}
        )
        self.lock_set.release_many(tx.transaction_id, sids)
        return tx


def _prepare_ok(gates: Mapping) -> bool:
    checks = [
        gates.get("identity_verified", True),
        gates.get("config_valid", True),
        gates.get("dependency_healthy", True),
        gates.get("blast_acceptable", True),
        gates.get("risk_acceptable", True),
        gates.get("consumer_known", True),
        gates.get("pre_health_ok", True),
        gates.get("rollback_proven", True),
        gates.get("approval_valid", True),
        gates.get("budget_available", True),
        gates.get("idempotency_claimable", True),
    ]
    return all(checks)


def _approval_expected(plan: MultiServiceChangePlan) -> dict:
    return {
        "transaction": plan.transaction_id,
        "service_set": ",".join(sp.service_id for sp in plan.service_set),
        "service_versions": ",".join(
            str(sp.service_profile_version) for sp in plan.service_set
        ),
        "operation_set": ",".join(plan.operation_set),
        "plan_hash": plan.plan_hash,
        "graph_digest": plan.dependency_graph_digest,
        "risk": plan.risk_after,
        "blast": plan.blast_radius,
    }


__all__ = [
    "MultiServiceCoordinator",
    "_GateContext",
]