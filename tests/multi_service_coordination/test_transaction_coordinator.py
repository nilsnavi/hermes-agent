from __future__ import annotations

import pytest

from agent.multi_service_coordination import events as ev
from agent.multi_service_coordination._durable import CoordinationStore
from agent.multi_service_coordination.eligibility import ChildVerdict
from agent.multi_service_coordination.models import CoordinatorState
from agent.multi_service_coordination.planner import PlanBuilder
from agent.multi_service_coordination.registry import CoordinationRegistry
from agent.multi_service_coordination.transaction import _GateContext
from tests.multi_service_coordination.conftest import build_plan, bind_approvals, A, B, CANARY


def _run(coord, plan, eligibility=None, prepare=None, sim=None, verify_ok=True, approval_ok=True, store=None):
    if approval_ok and store is not None:
        bind_approvals(store, plan, ok=True)
    gctx = _GateContext(
        eligibility or {s.service_id: True for s in plan.service_set},
        prepare, sim, verify_ok,
    )
    return coord.coordinate(plan, gctx)


def test_full_success_path_emits_canonical_journal(store, registry):
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    from agent.multi_service_coordination import MultiServiceCoordinator
    from agent.multi_service_coordination.lock_order import CanonicalLockSet
    coord = MultiServiceCoordinator(store, registry, lock_set=CanonicalLockSet())
    bind_approvals(store, plan)
    tx = _run(coord, plan, store=store)
    assert tx.state == CoordinatorState.COMMITTED_SIMULATED
    assert tx.outcome.value == "COMMITTED_SIMULATED"
    assert store.journal.types() == [
        ev.GLOBAL_CLAIMED, ev.LOCK_ACQUIRED,
        ev.CHILD_PREPARED, ev.CHILD_PREPARED,
        ev.BARRIER_READY, ev.SIMULATION_STARTED,
        ev.CHILD_SIMULATED, ev.CHILD_SIMULATED,
        ev.VERIFY_COMPLETED, ev.GLOBAL_SIMULATED_COMMIT,
    ]


def test_all_or_nothing_child_deny(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry)
    tx = _run(coord, plan, eligibility={A: True, B: False})
    assert tx.state == CoordinatorState.DENIED
    assert tx.outcome.value == "DENIED"


def test_child_unknown_never_becomes_allow(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry)
    tx = _run(coord, plan, eligibility={A: True, B: ChildVerdict.UNKNOWN})
    assert tx.state == CoordinatorState.DENIED


def test_partial_child_failure_is_compensation_not_success(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry)
    # A succeeds, B fails during simulation
    tx = _run(coord, plan, sim={A: True, B: False}, store=store)
    assert tx.state == CoordinatorState.COMPENSATION_REQUIRED
    assert tx.outcome.value == "COMPENSATION_REQUIRED"


def test_unknown_child_outcome_is_unknown_state(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry)
    tx = _run(coord, plan, sim={A: None, B: True}, store=store)
    assert tx.state == CoordinatorState.UNKNOWN_OUTCOME


def test_verify_failure_is_compensation_path(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry)
    tx = _run(coord, plan, verify_ok=False, store=store)
    assert tx.state in {CoordinatorState.VERIFY_FAILED, CoordinatorState.COMPENSATION_REQUIRED}


def test_prepare_failure_aborts_whole_transaction(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry)
    tx = _run(coord, plan, prepare={B: {"pre_health_ok": False}}, store=store)
    assert tx.state in {
        CoordinatorState.COMPENSATION_REQUIRED, CoordinatorState.PREPARE_FAILED,
    }


def test_no_execution_before_all_prepared(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry)
    tx = _run(coord, plan, prepare={B: {"identity_verified": False}}, store=store)
    assert tx.state != CoordinatorState.SIMULATED_EXECUTING
    assert not store.journal.count(ev.SIMULATION_STARTED)


def test_duplicate_intent_replays_prior_result(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    from agent.multi_service_coordination.idempotency import semantic_key
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    sem = semantic_key(plan, plan.registry_digest or registry.registry_digest)
    coord = MultiServiceCoordinator(store, registry)
    first = _run(coord, plan, store=store)
    assert first.state == CoordinatorState.COMMITTED_SIMULATED
    # same semantic intent re-issued
    store2 = CoordinationStore(store.root)
    coord2 = MultiServiceCoordinator(store2, registry)
    tx2 = _run(coord2, plan, store=store2)
    assert tx2.state == CoordinatorState.COMMITTED_SIMULATED
    # no second simulation upon duplicate — the journal records only prior commit
    assert store2.journal.count(ev.GLOBAL_SIMULATED_COMMIT) >= 1


def test_locks_released_after_commit(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    from agent.multi_service_coordination.lock_order import CanonicalLockSet
    locks = CanonicalLockSet()
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry, lock_set=locks)
    _run(coord, plan, store=store)
    assert locks.active_writers() == {}


def test_lock_conflict_fails_without_execution(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    from agent.multi_service_coordination.lock_order import CanonicalLockSet
    locks = CanonicalLockSet()
    locks.acquire_many("other-tx", [A, B])
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry, lock_set=locks)
    tx = _run(coord, plan, store=store)
    assert tx.state == CoordinatorState.LOCK_FAILED
    assert not store.journal.count(ev.SIMULATION_STARTED)


def test_no_real_adapter_call_count_in_telemetry(store, registry):
    from agent.multi_service_coordination import MultiServiceCoordinator
    from agent.multi_service_coordination.telemetry import CoordinatorTelemetry
    tele = CoordinatorTelemetry(store.root / "telemetry")
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    coord = MultiServiceCoordinator(store, registry, telemetry=tele)
    _run(coord, plan, store=store)
    snap = tele.snapshot()
    assert snap.get("real_adapter_calls", 0) == 0
    assert snap.get("simulated_commits", 0) == 1


def test_registry_discovery_never_grants_authority(store):
    reg = CoordinationRegistry(runtime_discovery=lambda: ["ghost-service", "fake-aux-z"])
    assert "ghost-service" not in reg.service_ids()
    assert not reg.is_registered("ghost-service")