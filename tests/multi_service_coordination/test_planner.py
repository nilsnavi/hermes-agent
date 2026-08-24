from __future__ import annotations

import pytest

from agent.multi_service_coordination.graph import DependencyGraph
from agent.multi_service_coordination.registry import CoordinationRegistry
from agent.multi_service_coordination.planner import PlanBuilder
from tests.multi_service_coordination.conftest import build_plan, make_subplan, A, B


def _builder():
    return PlanBuilder(CoordinationRegistry(), "baseline-sha")


def test_build_clean_plan_is_immutable_and_hashed():
    b = _builder()
    plan, err = build_plan(b)
    assert err is None
    assert plan.plan_hash == plan.compute_hash()  # frozen & self-consistent


def test_plan_service_set_mismatch_graph_denied():
    b = _builder()
    subplans = [make_subplan("fake-aux-a"), make_subplan("fake-aux-b")]
    g = DependencyGraph(service_ids=("fake-aux-a",), edges=())  # missing B
    _, err = b.build("tx", subplans, g)
    assert err == "SERVICE_SET_GRAPH_MISMATCH"


def test_unregistered_service_denied():
    b = _builder()
    g = DependencyGraph(service_ids=("ghost", "fake-aux-a"), edges=(("ghost", "fake-aux-a"),))
    plan, err = b.build("tx", [make_subplan("ghost"), make_subplan("fake-aux-a")], g)
    assert err == "UNREGISTERED_SERVICE"


def test_self_control_service_denied():
    b = _builder()
    g = DependencyGraph(service_ids=("hermes-gateway", "fake-aux-a"), edges=(("fake-aux-a", "hermes-gateway"),))
    plan, err = b.build("tx",
                        [make_subplan("hermes-gateway"), make_subplan("fake-aux-a")], g)
    assert err == "SELF_CONTROL_FORBIDDEN"


def test_hard_denied_target_denied():
    b = _builder()
    for target in ("hermes-gateway", "scheduler", "provider", "database", "docker", "ssh"):
        g = DependencyGraph(service_ids=(target,), edges=())
        plan, err = b.build("tx", [make_subplan(target)], g)
        assert err in {"HARD_DENIED_SERVICE", "SELF_CONTROL_FORBIDDEN"}, target


def test_blast_host_network_denied():
    b = _builder()
    for blast in ("HOST", "NETWORK", "UNKNOWN"):
        g = DependencyGraph(service_ids=("fake-aux-a",), edges=())
        plan, err = b.build("tx", [make_subplan("fake-aux-a", blast=blast)], g)
        assert err == "BLAST_RADIUS_DENIED"


def test_cycle_denied():
    b = _builder()
    g = DependencyGraph(service_ids=("fake-aux-a", "fake-aux-b"),
                        edges=(("fake-aux-a", "fake-aux-b"), ("fake-aux-b", "fake-aux-a")))
    plan, err = b.build("tx",
                        [make_subplan("fake-aux-a"), make_subplan("fake-aux-b")], g)
    assert err in {"CYCLE", "TRUE_CYCLE"}


def test_caller_desired_order_violation_denied():
    b = _builder()
    # fake-aux-b is a dependency of fake-aux-a => desired [A, B] is invalid
    g = DependencyGraph(service_ids=("fake-aux-a", "fake-aux-b"),
                        edges=(("fake-aux-a", "fake-aux-b"),))
    plan, err = b.build("tx",
                        [make_subplan("fake-aux-a"), make_subplan("fake-aux-b")],
                        g, desired_order=["fake-aux-a", "fake-aux-b"])
    assert err == "PLAN_INVALID"


def test_plan_freeze_prevents_edit():
    b = _builder()
    plan, err = build_plan(b)
    assert err is None
    with pytest.raises(Exception):
        plan.plan_id = "tampered"  # frozen dataclass


def test_parent_blast_is_max_plus_amplification():
    b = _builder()
    from tests.multi_service_coordination.conftest import A, B
    plan, err = build_plan(b, sids=(A, B))
    assert err is None
    assert plan.blast_radius == "MULTI_SERVICE"


def test_registry_digest_bound_into_plan():
    b = _builder()
    plan, err = build_plan(b)
    assert err is None
    assert plan.registry_digest == b.registry.registry_digest