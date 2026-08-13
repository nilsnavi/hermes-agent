"""ExecutionEngine tests (Sprint 1.0.2)."""

from datetime import datetime, timezone

import pytest

from agent.execution.approval import ApprovalManager, ApprovalStatus
from agent.execution.events import (
    EXECUTION_COMPLETED,
    PLAN_CREATED,
    STEP_APPROVED,
    STEP_REJECTED,
    STEP_STARTED,
    STEP_WAITING_APPROVAL,
    TOOL_COMPLETED,
    TOOL_FAILED,
    TOOL_STARTED,
)
from agent.execution.exceptions import ExecutionErrorBase
from agent.execution.executor import ExecutionEngine, MemoryExecutionStore
from agent.execution.models import PlanStatus, StepStatus
from agent.execution.planner import ExecutionPlanner
from agent.execution.registry import ToolRegistry
from agent.execution.tool_runtime import ToolRuntime
from agent.runtime.context import TaskContext
from agent.runtime.events import RuntimeEvent
from agent.runtime.run_engine import RunEngine


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def _echo(args, ctx):
    return {"echo": args.get("q", ""), "ran": True}


def _boom(args, ctx):
    raise ValueError("boom")


def _nothing(args, ctx):
    return None


def _registry(handlers=None):
    reg = ToolRegistry()
    reg.register("github", _echo)
    reg.register("llm", _echo)
    reg.register("telegram", _echo)
    for name, handler in (handlers or {}).items():
        reg.register(name, handler)
    return reg


def _context(approval_required=False):
    return TaskContext(
        goal="Send daily report",
        allowed_tools=["github", "llm", "telegram"],
        approval_required=approval_required,
    )


def _plan(clock=None, steps=None, ctx=None, run_id="run-1"):
    planner = ExecutionPlanner(clock=clock or _Clock())
    return planner.create_plan(
        run_id,
        ctx or _context(),
        steps
        if steps is not None
        else [
            {"name": "collect_data", "tool": "github", "arguments": {"q": "data"}},
            {"name": "generate_report", "tool": "llm"},
            {"name": "send_message", "tool": "telegram"},
        ],
        plan_id="plan-1",
    )


def _plan_gated(clock=None):
    """Plan whose last step requires approval (execution pauses at step-3)."""
    return _plan(
        clock=clock,
        steps=[
            {"name": "collect_data", "tool": "github"},
            {"name": "generate_report", "tool": "llm"},
            {"name": "send_message", "tool": "telegram", "requires_approval": True},
        ],
    )


def _engine(registry=None, store=None, events=None, clock=None):
    runtime = ToolRuntime(registry or _registry(), timeout=0.5)
    approvals = ApprovalManager(clock=clock or _Clock())
    return ExecutionEngine(
        runtime,
        approval_manager=approvals,
        store=store,
        clock=clock or _Clock(),
        events=events,
    )


def test_full_lifecycle_success():
    engine = _engine()
    plan = _plan()
    engine.execute_plan(plan)
    assert plan.status is PlanStatus.COMPLETED
    assert plan.completed_at is not None
    assert plan.started_at is not None
    assert all(s.status is StepStatus.COMPLETED for s in plan.steps)


def test_step_results_saved():
    engine = _engine()
    plan = _plan()
    engine.execute_plan(plan)
    assert plan.steps[0].result is not None
    assert plan.steps[0].result["status"] == "success"
    assert plan.steps[0].result["output"]["ran"] is True
    assert plan.steps[1].result is not None
    assert plan.steps[1].result["output"]["echo"] == ""


def test_full_lifecycle_events_order():
    events: list[RuntimeEvent] = []
    engine = _engine(events=events)
    plan = _plan()
    engine.execute_plan(plan)
    types = [e.event_type for e in events]
    assert types[0] == PLAN_CREATED
    assert types.count(STEP_STARTED) == 3
    assert types.count(TOOL_STARTED) == 3
    assert types.count(TOOL_COMPLETED) == 3
    assert types[-1] == EXECUTION_COMPLETED
    # interleaving: every TOOL_STARTED precedes its TOOL_COMPLETED
    for i, t in enumerate(types):
        if t == TOOL_COMPLETED:
            assert TOOL_STARTED in types[:i]
    assert all(e.run_id == "run-1" for e in events)


def test_approval_gate_pauses_execution():
    counter = {"n": 0}

    def _counted(args, ctx):
        counter["n"] += 1
        return {"ok": 1}

    reg = _registry(
        handlers={"github": _counted, "llm": _counted, "telegram": _counted}
    )
    engine = _engine(registry=reg)
    plan = _plan_gated()
    engine.execute_plan(plan)
    assert plan.status is PlanStatus.RUNNING
    assert plan.steps[0].status is StepStatus.COMPLETED
    assert plan.steps[1].status is StepStatus.COMPLETED
    assert plan.steps[2].status is StepStatus.WAITING_APPROVAL
    assert counter["n"] == 2  # telegram never ran


def test_approval_gate_creates_pending_request():
    engine = _engine()
    plan = _plan_gated()
    engine.execute_plan(plan)
    pending = engine.approvals.list_pending()
    assert len(pending) == 1
    assert pending[0].step_id == "step-3"
    assert pending[0].status is ApprovalStatus.PENDING


def test_approve_resumes_and_completes():
    engine = _engine()
    plan = _plan_gated()
    engine.execute_plan(plan)
    approval = engine.approvals.list_pending()[0]
    engine.approve_step(plan, approval.id)
    assert plan.status is PlanStatus.COMPLETED
    assert plan.steps[2].status is StepStatus.COMPLETED
    assert plan.steps[2].result is not None


def test_approve_emits_event():
    events: list[RuntimeEvent] = []
    engine = _engine(events=events)
    plan = _plan_gated()
    engine.execute_plan(plan)
    approval = engine.approvals.list_pending()[0]
    engine.approve_step(plan, approval.id)
    assert STEP_APPROVED in [e.event_type for e in events]
    assert STEP_WAITING_APPROVAL in [e.event_type for e in events]


def test_reject_fails_plan_and_skips_remaining():
    engine = _engine()
    plan = _plan_gated()
    engine.execute_plan(plan)
    approval = engine.approvals.list_pending()[0]
    engine.reject_step(plan, approval.id)
    assert plan.status is PlanStatus.FAILED
    assert plan.steps[2].status is StepStatus.SKIPPED
    assert plan.steps[2].error == "rejected by user"


def test_reject_emits_event():
    events: list[RuntimeEvent] = []
    engine = _engine(events=events)
    plan = _plan_gated()
    engine.execute_plan(plan)
    approval = engine.approvals.list_pending()[0]
    engine.reject_step(plan, approval.id)
    assert STEP_REJECTED in [e.event_type for e in events]


def test_tool_failure_fails_plan():
    engine = _engine(registry=_registry(handlers={"llm": _boom}))
    plan = _plan()
    engine.execute_plan(plan)
    assert plan.status is PlanStatus.FAILED
    assert plan.steps[0].status is StepStatus.COMPLETED
    assert plan.steps[1].status is StepStatus.FAILED
    assert plan.steps[1].error == "boom"
    assert plan.steps[2].status is StepStatus.PENDING  # untouched


def test_tool_failure_emits_tool_failed():
    events: list[RuntimeEvent] = []
    engine = _engine(registry=_registry(handlers={"llm": _boom}), events=events)
    plan = _plan()
    engine.execute_plan(plan)
    types = [e.event_type for e in events]
    assert TOOL_FAILED in types
    assert EXECUTION_COMPLETED not in types


def test_partial_completion_preserves_done_steps():
    engine = _engine(registry=_registry(handlers={"telegram": _boom}))
    plan = _plan(steps=[
        {"name": "a", "tool": "github"},
        {"name": "b", "tool": "telegram"},
        {"name": "c", "tool": "llm"},
    ])
    engine.execute_plan(plan)
    assert plan.steps[0].status is StepStatus.COMPLETED
    assert plan.steps[1].status is StepStatus.FAILED
    assert plan.steps[2].status is StepStatus.PENDING


def test_cancel_plan():
    engine = _engine()
    plan = _plan_gated()
    engine.execute_plan(plan)  # pauses at approval
    engine.cancel_plan(plan)
    assert plan.status is PlanStatus.CANCELLED
    assert plan.steps[0].status is StepStatus.COMPLETED
    assert plan.steps[1].status is StepStatus.COMPLETED
    assert plan.steps[2].status is StepStatus.SKIPPED


def test_execute_finished_plan_raises():
    engine = _engine()
    plan = _plan()
    engine.execute_plan(plan)
    with pytest.raises(ExecutionErrorBase):
        engine.execute_plan(plan)


def test_unknown_tool_fails_step_not_allowed():
    reg = _registry(handlers={"telegram": _echo})
    plan = _plan(steps=[{"name": "x", "tool": "telegram"}])
    # drop telegram from the registry to make it unknown
    plan.steps[0].tool = "not-registered"
    engine = _engine(registry=reg)
    engine.execute_plan(plan)
    assert plan.status is PlanStatus.FAILED
    assert plan.steps[0].status is StepStatus.FAILED
    assert "not allowed" in (plan.steps[0].error or "")


def test_verifier_rejects_missing_output():
    engine = _engine(registry=_registry(handlers={"llm": _nothing}))
    plan = _plan(steps=[
        {"name": "a", "tool": "github"},
        {"name": "b", "tool": "llm"},
    ])
    engine.execute_plan(plan)
    assert plan.status is PlanStatus.FAILED
    assert plan.steps[1].status is StepStatus.FAILED
    assert "output is missing" in (plan.steps[1].error or "")


def test_store_persists_plan_and_steps():
    store = MemoryExecutionStore()
    engine = _engine(store=store)
    plan = _plan()
    engine.execute_plan(plan)
    assert store.get_plan("plan-1").status is PlanStatus.COMPLETED
    stored_step = store.get_step("plan-1", "step-1")
    assert stored_step.status is StepStatus.COMPLETED
    assert stored_step.result is not None
    assert stored_step.result["output"]["ran"] is True


def test_store_get_plan_missing_raises():
    store = MemoryExecutionStore()
    with pytest.raises(ExecutionErrorBase):
        store.get_plan("nope")


def test_shared_event_trail_with_run_engine():
    """Execution events reuse the RuntimeEvent stream (Sprint 1.0.1 object)."""
    trail: list[RuntimeEvent] = []
    run_engine = RunEngine(events=trail)
    run = run_engine.create_run("report", "BALANCED", run_id="run-1")
    exec_engine = _engine(events=trail)
    plan = _plan(run_id="run-1")
    exec_engine.execute_plan(plan)
    assert len(trail) >= 10
    assert trail[0].event_type == "RUN_CREATED"
    assert all(isinstance(e, RuntimeEvent) for e in trail)
    assert all(e.run_id == "run-1" for e in trail)
    assert any(e.event_type == EXECUTION_COMPLETED for e in trail)


def test_approve_unknown_id_raises():
    engine = _engine()
    plan = _plan_gated()
    engine.execute_plan(plan)
    with pytest.raises(KeyError):
        engine.approve_step(plan, "approval-999")


def test_execution_time_in_step_result():
    engine = _engine()
    plan = _plan()
    engine.execute_plan(plan)
    assert plan.steps[0].result is not None
    assert plan.steps[0].result["execution_time"] >= 0.0


def test_plan_serialization_after_execution():
    engine = _engine()
    plan = _plan()
    engine.execute_plan(plan)
    restored = plan.to_dict()
    assert restored["status"] == "completed"
    assert restored["steps"][0]["status"] == "completed"
    assert restored["steps"][0]["result"] is not None
    assert restored["steps"][0]["result"]["output"]["ran"] is True
