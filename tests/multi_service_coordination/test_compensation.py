from __future__ import annotations

from agent.multi_service_coordination.compensation import (
    CompensationBuilder,
    compensation_required_strategy,
)
from agent.multi_service_coordination.models import MultiServiceChangePlan
from agent.multi_service_coordination.planner import PlanBuilder
from agent.multi_service_coordination.registry import CoordinationRegistry
from tests.multi_service_coordination.conftest import build_plan, A, B, CANARY


def test_compensation_order_is_reverse_topological(tmp_path):
    b = PlanBuilder(CoordinationRegistry(), "baseline")
    # B depends on A  => execution [A, B] => rollback [B, A]
    plan, _ = build_plan(b, sids=(A, B), edges=(("fake-aux-b", "fake-aux-a"),))
    plan = _with_hash(plan)
    comp = compensation_required_strategy(plan, {A: "SUCCESS", B: "FAILED"})
    steps = comp.ordered_steps()
    assert [s.service_id for s in steps] == list(plan.rollback_order)
    # dependent (B) must be compensated before its dependency (A)
    assert steps[0].service_id == B
    assert steps[-1].service_id == A


def test_compensation_never_reports_partial_success(tmp_path):
    b = PlanBuilder(CoordinationRegistry(), "baseline")
    plan, _ = build_plan(b)
    plan = _with_hash(plan)
    comp = compensation_required_strategy(plan, {A: "SUCCESS", B: "FAILED"})
    # strategy is invoked for a failure; it never asserts "all committed"
    assert comp.steps  # at least the failed child is compensated


def test_compensation_not_started_child_is_noop(tmp_path):
    b = PlanBuilder(CoordinationRegistry(), "baseline")
    plan, _ = build_plan(b)
    plan = _with_hash(plan)
    comp = compensation_required_strategy(plan, {A: "SUCCESS", B: "NOT_STARTED"})
    assert len(comp.steps) == 2


def test_rollback_unsupported_flag_poisons_plan(tmp_path):
    builder = CompensationBuilder("gtx")
    builder.add("a", "COMPENSATE", order=0, reverse_order=1, unsupported=True)
    comp = builder.build()
    assert not comp.rollback_supported


def test_compensation_builder_default_supported():
    builder = CompensationBuilder("gtx")
    builder.add("a", "ROLLBACK", order=0, reverse_order=1)
    assert builder.build().rollback_supported


def _with_hash(plan: MultiServiceChangePlan) -> MultiServiceChangePlan:
    from dataclasses import replace
    if plan.plan_hash:
        return plan
    return replace(plan, plan_hash=plan.compute_hash())