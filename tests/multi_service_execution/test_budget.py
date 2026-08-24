"""Sprint 1.3.17 — aggregate execution budget (§16)."""

from __future__ import annotations

from agent.multi_service_execution import (ExecutionBudget, ExecutionBudgetLimits)
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def test_no_double_reserve():
    b = ExecutionBudget()
    assert b.reserve("p1", 2).allowed is True
    assert b.reserve("p1", 2).reason == "already-reserved"


def test_no_double_consume():
    b = ExecutionBudget()
    b.reserve("p1", 2)
    assert b.consume("p1").allowed is True
    assert b.consume("p1").reason == "already-consumed"


def test_max_services_bounded():
    b = ExecutionBudget(ExecutionBudgetLimits(max_services=3))
    assert b.reserve("big", 3).allowed is True
    assert b.reserve("big2", 4).reason.startswith("too-many-services")


def test_consume_requires_reserve():
    b = ExecutionBudget()
    assert b.consume("nope").reason == "not-reserved"


def test_cannot_release_consumed():
    b = ExecutionBudget()
    b.reserve("p", 1)
    b.consume("p")
    assert b.release("p").reason == "cannot-release-consumed"


def test_budget_not_reserved_blocks_pipeline(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan),
                         budgets_reserved=False)
    assert r["adapter_call_count"] == 0
    assert r["global_state"] == "EXECUTION_DENIED"