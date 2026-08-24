from __future__ import annotations

"""Property / invariant tests (brief §45).  Each invariant is asserted directly."""
from agent.multi_service_coordination._durable import CoordinationStore
from agent.multi_service_coordination.eligibility import ChildVerdict, aggregate_eligibility
from agent.multi_service_coordination.graph import DependencyGraph, topological_order
from agent.multi_service_coordination.idempotency import semantic_key
from agent.multi_service_coordination.lock_order import CanonicalLockSet
from agent.multi_service_coordination import MultiServiceCoordinator
from agent.multi_service_coordination.models import CoordinatorState
from agent.multi_service_coordination.planner import PlanBuilder
from agent.multi_service_coordination.registry import CoordinationRegistry
from agent.multi_service_coordination.risk import risk_monotonic
from agent.multi_service_coordination.transaction import _GateContext
from tests.multi_service_coordination.conftest import build_plan, bind_approvals, A, B, CANARY


def test_at_most_one_global_owner_per_semantic_intent(tmp_path):
    store = CoordinationStore(tmp_path / "s")
    key = "intent-1"
    assert store.claim_global(key, "tx-A") == "CLAIMED_BY_ME"
    assert store.claim_global(key, "tx-B") == "CLAIMED_BY_OTHER"
    assert store.claim_global(key, "tx-A") == "ALREADY_MINE"


def test_at_most_one_active_writer_per_service():
    locks = CanonicalLockSet()
    assert locks.acquire_many("t1", ["fake-aux-a"]) is not None
    assert not locks.acquire_many("t2", ["fake-aux-a"])
    locks.release_many("t1", ["fake-aux-a"])


def test_no_execution_before_all_prepared(tmp_path, registry):
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    store = CoordinationStore(tmp_path / "s")
    coord = MultiServiceCoordinator(store, registry)
    bind_approvals(store, plan)
    tx = coord.coordinate(plan, _GateContext(
        {A: True, B: True}, prepare_gates={B: {"identity_verified": False}}
    ))
    assert tx.state != CoordinatorState.SIMULATED_EXECUTING
    assert store.journal.count("SIMULATION_STARTED") == 0


def test_no_partial_success(tmp_path, registry):
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    store = CoordinationStore(tmp_path / "s")
    coord = MultiServiceCoordinator(store, registry)
    bind_approvals(store, plan)
    tx = coord.coordinate(plan, _GateContext(
        {A: True, B: True}, sim_outcome={A: True, B: False}
    ))
    # A succeeded alone => must NOT be COMMITTED_SIMULATED
    assert tx.state != CoordinatorState.COMMITTED_SIMULATED


def test_deny_propagates_upward():
    agg = aggregate_eligibility({"a": True, "b": False, "c": True})
    assert not agg.allowed


def test_unknown_never_becomes_allow():
    agg = aggregate_eligibility({"a": True, "b": ChildVerdict.UNKNOWN})
    assert not agg.allowed
    assert agg.reason.value == "REVALIDATE_REQUIRED"


def test_risk_never_decreases():
    assert risk_monotonic(["LOW", "HIGH"])
    assert risk_monotonic(["MEDIUM", "HIGH"])
    assert risk_monotonic(["HIGH"])


def test_blast_never_reduced_incorrectly_for_multi(tmp_path):
    b = PlanBuilder(CoordinationRegistry(), "baseline")
    plan, err = build_plan(b, sids=(A, B))
    assert err is None
    assert plan.blast_radius == "MULTI_SERVICE"  # amplification, never lower


def test_registry_discovery_never_grants_authority():
    reg = CoordinationRegistry(runtime_discovery=lambda: ["ghost", "gateway", "production-db"])
    for sid in ("ghost", "gateway", "production-db"):
        assert not reg.is_registered(sid)


def test_replay_never_duplicates_accounting(tmp_path, registry):
    b = PlanBuilder(registry, "baseline")
    plan, _ = build_plan(b)
    store = CoordinationStore(tmp_path / "s")
    coord = MultiServiceCoordinator(store, registry)
    bind_approvals(store, plan)
    coord.coordinate(plan, _GateContext({A: True, B: True}))
    bind_approvals(store, plan)
    coord.coordinate(plan, _GateContext({A: True, B: True}))  # duplicate
    # exactly one simulated commit was recorded
    assert store.journal.count("GLOBAL_SIMULATED_COMMIT") == 1


def test_cycle_never_executes():
    g = DependencyGraph(service_ids=(A, B),
                        edges=(("fake-aux-a", "fake-aux-b"), ("fake-aux-b", "fake-aux-a")))
    assert topological_order(g) is None
    reg = CoordinationRegistry()
    b = PlanBuilder(reg, "baseline")
    from agent.multi_service_coordination.graph import GraphStatus
    assert g.validated(reg).status == GraphStatus.CYCLE