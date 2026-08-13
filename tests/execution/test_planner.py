"""ExecutionPlanner tests (Sprint 1.0.2)."""

from datetime import datetime, timezone

import pytest

from agent.execution.exceptions import InvalidPlan
from agent.execution.models import PlanStatus, StepStatus
from agent.execution.planner import ExecutionPlanner
from agent.runtime.context import TaskContext

CLOCK = lambda: datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731

STEPS = [
    {"name": "collect_data", "tool": "github", "arguments": {"repo": "navitech"}},
    {"name": "generate_report", "tool": "llm"},
    {"name": "send_message", "tool": "telegram", "requires_approval": True},
]


def _ctx(approval_required: bool = False, allowed_tools=None):
    return TaskContext(
        goal="Send daily report",
        allowed_tools=allowed_tools or ["github", "llm", "telegram"],
        approval_required=approval_required,
    )


def _plan(steps=None, ctx=None, **kwargs):
    return ExecutionPlanner(clock=CLOCK).create_plan(
        "run-1", ctx or _ctx(), steps if steps is not None else STEPS, **kwargs
    )


def test_create_plan_basic():
    plan = _plan()
    assert plan.run_id == "run-1"
    assert plan.goal == "Send daily report"
    assert plan.status is PlanStatus.CREATED
    assert plan.created_at == CLOCK()
    assert len(plan.steps) == 3


def test_first_step_ready_rest_pending():
    plan = _plan()
    assert plan.steps[0].status is StepStatus.READY
    assert all(s.status is StepStatus.PENDING for s in plan.steps[1:])


def test_step_order_preserved():
    plan = _plan()
    assert [s.name for s in plan.steps] == [
        "collect_data", "generate_report", "send_message",
    ]
    assert [s.tool for s in plan.steps] == ["github", "llm", "telegram"]


def test_step_ids_sequential():
    plan = _plan()
    assert [s.id for s in plan.steps] == ["step-1", "step-2", "step-3"]


def test_arguments_roundtrip():
    plan = _plan()
    assert plan.steps[0].arguments == {"repo": "navitech"}
    assert plan.steps[1].arguments == {}


def test_requires_approval_from_step():
    plan = _plan()
    assert plan.steps[0].requires_approval is False
    assert plan.steps[2].requires_approval is True


def test_approval_propagates_from_context():
    plan = _plan(ctx=_ctx(approval_required=True))
    assert all(s.requires_approval for s in plan.steps)


def test_explicit_plan_id():
    assert _plan(plan_id="plan-77").id == "plan-77"


def test_invalid_plan_empty_steps():
    with pytest.raises(InvalidPlan):
        _plan(steps=[])


def test_invalid_plan_missing_name():
    with pytest.raises(InvalidPlan, match="name"):
        _plan(steps=[{"tool": "github"}])


def test_invalid_plan_missing_tool():
    with pytest.raises(InvalidPlan, match="tool"):
        _plan(steps=[{"name": "x"}])


def test_invalid_plan_tool_not_in_allowlist():
    with pytest.raises(InvalidPlan, match="not in allowed_tools"):
        _plan(steps=[{"name": "x", "tool": "ssh"}])


def test_invalid_plan_arguments_not_dict():
    with pytest.raises(InvalidPlan, match="arguments"):
        _plan(steps=[{"name": "x", "tool": "github", "arguments": "nope"}])


def test_plan_serialization_roundtrip():
    plan = _plan()
    data = plan.to_dict()
    from agent.execution.models import ExecutionPlan

    restored = ExecutionPlan.from_dict(data)
    assert restored.id == plan.id
    assert restored.goal == plan.goal
    assert [s.name for s in restored.steps] == [s.name for s in plan.steps]
    assert restored.steps[2].requires_approval is True
    assert restored.status is PlanStatus.CREATED
