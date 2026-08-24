"""Shared fixture helpers for Sprint 1.3.15 coordination tests."""
from __future__ import annotations

import pytest

from agent.multi_service_coordination._durable import CoordinationStore
from agent.multi_service_coordination.graph import DependencyGraph
from agent.multi_service_coordination.models import ServiceSubPlan
from agent.multi_service_coordination.planner import PlanBuilder
from agent.multi_service_coordination.registry import CoordinationRegistry
from agent.multi_service_coordination.transaction import MultiServiceCoordinator, _GateContext
from agent.multi_service_coordination.lock_order import CanonicalLockSet

CANARY = "hermes-aux-canary"
A = "fake-aux-a"
B = "fake-aux-b"


def make_subplan(sid: str, op: str = "RESTART", blast="SERVICE", risk="HIGH") -> ServiceSubPlan:
    return ServiceSubPlan(
        service_id=sid,
        service_profile_version=1,
        operation=op,
        identity_fingerprint=f"id-{sid}",
        config_fingerprint=f"cfg-{sid}",
        dependency_digest="dep",
        pre_health="GREEN",
        required_post_health="GREEN",
        rollback_strategy="snapshot",
        risk=risk,
        blast_radius=blast,
        consumer_set=("none",),
        approval_reference=f"ap-{sid}",
        budget_reference=f"bud-{sid}",
        idempotency_key=f"sk-{sid}",
    )


def chain_graph(sids=(A, B), edges=None) -> DependencyGraph:
    edges = edges if edges is not None else ((A, B),)
    return DependencyGraph(service_ids=tuple(sids), edges=tuple(edges))


def build_plan(builder: PlanBuilder, sids=(A, B), op="RESTART", edges=None, blasts=None, risks=None):
    blasts = blasts or {}
    risks = risks or {}
    subplans = [
        make_subplan(sid, op=op, blast=blasts.get(sid, "SERVICE"), risk=risks.get(sid, "HIGH"))
        for sid in sids
    ]
    graph = chain_graph(sids, edges)
    return builder.build(f"tx-{'-'.join(sids)}-{id(subplans)}", subplans, graph)


def bind_approvals(store: CoordinationStore, plan, ok=True) -> None:
    for spn in plan.service_set:
        binding = {
            "transaction": plan.transaction_id,
            "service_set": ",".join(s.service_id for s in plan.service_set),
            "service_versions": ",".join(str(s.service_profile_version) for s in plan.service_set),
            "operation_set": ",".join(plan.operation_set),
            "plan_hash": plan.plan_hash,
            "graph_digest": plan.dependency_graph_digest,
            "risk": plan.risk_after,
            "blast": plan.blast_radius,
        }
        if not ok:
            binding["plan_hash"] = "drifted"
        store.bind_approval(spn.approval_reference, binding)


@pytest.fixture
def coord(tmp_path):
    store = CoordinationStore(tmp_path / "store")
    reg = CoordinationRegistry()
    return MultiServiceCoordinator(store, reg, lock_set=CanonicalLockSet())


@pytest.fixture
def store(tmp_path):
    return CoordinationStore(tmp_path / "store")


@pytest.fixture
def registry():
    return CoordinationRegistry()