"""Plan validation tests (Sprint 1.0.5 §43-45)."""

import pytest

from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from agent.orchestrator import ExecutionPolicy, PlanValidator, StopReason
from agent.runtime.context import TaskContext

from tests.orchestrator.conftest import T0, make_orchestrator, spec


def _plan(steps):
    return ExecutionPlan(id="plan-1", run_id="run-1", goal="g",
                         status=PlanStatus.RUNNING, created_at=T0, steps=steps)


def _step(step_id, tool, **kw):
    return ExecutionStep(id=step_id, name=step_id, description="", tool=tool, **kw)


def test_valid_plan_no_issues(registry):
    plan = _plan([_step("s1", "search"), _step("s2", "fetch")])
    assert PlanValidator(registry).validate(plan) == []


def test_duplicate_step_ids_detected(registry):
    plan = _plan([_step("s1", "search"), _step("s1", "fetch")])
    issues = PlanValidator(registry).validate(plan)
    assert any("duplicate" in i for i in issues)


def test_unknown_tool_detected(registry):
    plan = _plan([_step("s1", "not_a_real_tool")])
    issues = PlanValidator(registry).validate(plan)
    assert any("unknown tool" in i for i in issues)


def test_allowed_tools_fail_closed(registry):
    """§45 — even a registered tool outside allowed_tools is invalid."""
    plan = _plan([_step("s1", "search")])
    ctx = TaskContext(goal="g", allowed_tools=["fetch"])  # search NOT allowed
    issues = PlanValidator(registry).validate(plan, ctx)
    assert any("not in allowed_tools" in i for i in issues)
    assert PlanValidator(registry).is_valid(plan, ctx) is False


def test_empty_plan_invalid(registry):
    issues = PlanValidator(registry).validate(_plan([]))
    assert issues == ["plan has no steps"]


def test_invalid_plan_executes_zero_tools(store, registry, clock):
    """Acceptance 20 — invalid plan → INVALID_PLAN, ZERO tool calls."""
    orch = make_orchestrator(store, registry, clock)
    ctx = TaskContext(goal="g", allowed_tools=["ghost_tool"])  # passes planner
    result = orch.run(ctx, ExecutionPolicy(), [{"name": "s", "tool": "ghost_tool"}])

    assert result.stop_reason is StopReason.INVALID_PLAN
    assert result.tool_calls == 0
    assert store.get_run(result.run_id).status.value == "failed"
    assert store.list_events(run_id=result.run_id)  # run exists, zero TOOL events


def test_allowed_tools_enforced_at_run(store, registry, clock):
    """Acceptance 15 — plan tool outside allowed_tools → zero execution."""
    orch = make_orchestrator(store, registry, clock)
    ctx = TaskContext(goal="g", allowed_tools=["search"])
    result = orch.run(ctx, ExecutionPolicy(),
                      [{"name": "s", "tool": "delete"}])  # registered but not allowed

    assert result.stop_reason is StopReason.INVALID_PLAN
    assert result.tool_calls == 0


def test_empty_step_specs_is_no_plan(store, registry, clock):
    """§42 — a task expecting execution with no steps → NO_PLAN."""
    orch = make_orchestrator(store, registry, clock)
    ctx = TaskContext(goal="g", allowed_tools=["search"])
    result = orch.run(ctx, ExecutionPolicy(), [])

    assert result.stop_reason is StopReason.NO_PLAN
    assert store.get_run(result.run_id).status.value == "failed"
