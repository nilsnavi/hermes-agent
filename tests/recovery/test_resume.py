"""Resume coordinator tests (Sprint 1.0.4) — the safety core.

Every test constructs a realistic crash state in a SQLite store, then asks
the coordinator to resume with a FRESH engine. Tool call counters prove
nothing is ever re-run with unknown outcome.
"""

from datetime import datetime, timezone

import pytest

from agent.execution import ExecutionEngine, ExecutionPlanner, ToolRegistry, ToolRuntime
from agent.execution.approval import ApprovalRequest, ApprovalStatus
from agent.execution.exceptions import ExecutionErrorBase
from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from agent.persistence import SQLiteExecutionStore
from agent.recovery import ResumeCoordinator
from agent.recovery.exceptions import RecoveryErrorBase
from agent.runtime.context import TaskContext
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.run_engine import RunEngine
from agent.runtime.states import RunStatus

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
CLOCK = lambda: T0  # noqa: E731


# ── helpers ──────────────────────────────────────────────────────────

def _registry(handlers=None):
    reg = ToolRegistry()
    reg.register("github", lambda a, c: {"commits": 1})
    reg.register("llm", lambda a, c: {"report": "ok"})
    reg.register("telegram", lambda a, c: {"sent": True})
    for name, handler in (handlers or {}).items():
        reg.register(name, handler)
    return reg


def _engine(store, handlers=None):
    return ExecutionEngine(ToolRuntime(_registry(handlers), timeout=5),
                           store=store, clock=CLOCK)


def _run_engine(store):
    return RunEngine(clock=CLOCK, store=store)


def _event(event_type, run_id, step=None):
    payload = {"step": step} if step else {}
    return RuntimeEvent(event_type=event_type, run_id=run_id,
                        timestamp=T0, payload=payload)


def _build_run(store, statuses, run_id="run-1"):
    """Drive a run through the state machine; returns the run object."""
    engine = _run_engine(store)
    run = engine.create_run("report", "BALANCED", run_id=run_id)
    for target in statuses:
        engine.transition(run, target)
    return run


def _save_plan(store, run_id, steps, plan_id="plan-1", plan_status=PlanStatus.RUNNING):
    plan = ExecutionPlan(id=plan_id, run_id=run_id, goal="g",
                         status=plan_status, created_at=T0)
    store.save_plan(plan)
    for step in steps:
        store.save_step(plan_id, step)
    return plan


def _step(step_id, status=StepStatus.PENDING, result=None, tool="github"):
    return ExecutionStep(id=step_id, name=step_id, description="",
                         tool=tool, status=status, result=result)


@pytest.fixture
def store(tmp_path):
    s = SQLiteExecutionStore(str(tmp_path / "state.db"))
    yield s
    s.close()


# ── safe resume ──────────────────────────────────────────────────────

def test_resume_after_crash_between_steps(store):
    """Crash after step-1 committed, before step-2 started."""
    run = _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING,
                             RunStatus.RUNNING])
    calls = {"n": 0}
    def _step2(args, ctx):
        calls["n"] += 1
        return {"done": True}
    plan = _save_plan(store, "run-1", [
        _step("s1", StepStatus.COMPLETED, result={"commits": 1}),
        _step("s2", StepStatus.PENDING, tool="llm"),
        _step("s3", StepStatus.PENDING, tool="telegram"),
    ])
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "PLAN_CREATED", "STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED"):
        store.append_event(_event(e, "run-1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1", engine=_engine(store, {"llm": _step2}))

    assert result.action == "completed"
    assert store.get_run("run-1").status is RunStatus.COMPLETED
    plan = store.get_plan("plan-1")
    assert [s.status for s in plan.steps] == [
        StepStatus.COMPLETED, StepStatus.COMPLETED, StepStatus.COMPLETED,
    ]
    assert plan.steps[1].result["output"] == {"done": True}
    assert calls["n"] == 1  # step-2 ran exactly once
    run_result = store.get_run("run-1").result
    assert set(run_result) == {"s1", "s2", "s3"}
    assert run_result["s2"]["output"] == {"done": True}
    assert run_result["s3"]["output"] == {"sent": True}


def test_resume_does_not_repeat_completed_tools(store):
    """Completed steps must never re-execute their tools."""
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING])
    calls = {"s1": 0, "s2": 0}
    def _c1(args, ctx):
        calls["s1"] += 1
        return {"ok": 1}
    def _c2(args, ctx):
        calls["s2"] += 1
        return {"ok": 2}
    _save_plan(store, "run-1", [
        _step("s1", StepStatus.COMPLETED, result={"ok": 1}),
        _step("s2", StepStatus.PENDING, tool="llm"),
    ])
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "PLAN_CREATED", "STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED"):
        store.append_event(_event(e, "run-1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    coordinator.resume("run-1", engine=_engine(store, {"github": _c1, "llm": _c2}))

    assert calls["s1"] == 0  # completed step untouched
    assert calls["s2"] == 1


def test_resume_ready_without_engine_executes_nothing(store):
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING])
    calls = {"n": 0}
    def _tool(args, ctx):
        calls["n"] += 1
        return {"ok": 1}
    _save_plan(store, "run-1", [_step("s1", StepStatus.PENDING)])
    store.append_event(_event("RUN_CREATED", "run-1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1")  # no engine

    assert result.action == "resume_ready"
    assert calls["n"] == 0
    assert store.get_run("run-1").status is RunStatus.RUNNING
    # nothing new in the journal beyond the scan-free call (no RESUME event)
    assert not [e for e in store.list_events(run_id="run-1")
                if e.event_type == "RECOVERY_RESUMED"]


# ── approval preservation ────────────────────────────────────────────

def test_waiting_approval_keeps_existing_approval(store):
    """No duplicate approval request — the run keeps waiting."""
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING,
                       RunStatus.WAITING_APPROVAL])
    _save_plan(store, "run-1", [_step("s1", StepStatus.WAITING_APPROVAL)])
    store.save_approval(ApprovalRequest(id="approval-1", run_id="run-1",
                                        step_id="s1", status=ApprovalStatus.PENDING,
                                        created_at=T0))
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "PLAN_CREATED", "STEP_STARTED", "STEP_WAITING_APPROVAL"):
        store.append_event(_event(e, "run-1", step="s1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1", engine=_engine(store))

    assert result.action == "wait"
    approvals = store.list_approvals(run_id="run-1")
    assert len(approvals) == 1  # still ONE approval — no duplicate
    assert approvals[0].status is ApprovalStatus.PENDING
    event_types = [e.event_type for e in store.list_events(run_id="run-1")]
    assert event_types.count("STEP_WAITING_APPROVAL") == 1  # not re-emitted
    assert "RECOVERY_WAITING" in event_types


# ── unknown tool outcome ─────────────────────────────────────────────

def test_tool_execution_crash_no_automatic_retry(store):
    """TOOL_STARTED without TOOL_COMPLETED → manual review, never re-run."""
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING,
                       RunStatus.RUNNING, RunStatus.TOOL_EXECUTION])
    calls = {"n": 0}
    def _exploding(args, ctx):
        calls["n"] += 1
        return {"ok": 1}
    _save_plan(store, "run-1", [_step("s1", StepStatus.RUNNING, tool="github")])
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "STATE_CHANGED", "PLAN_CREATED", "STEP_STARTED", "TOOL_STARTED"):
        store.append_event(_event(e, "run-1", step="s1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1", engine=_engine(store, {"github": _exploding}))

    assert result.action == "manual_review"
    assert calls["n"] == 0  # tool NEVER re-run
    assert store.get_run("run-1").status is RunStatus.TOOL_EXECUTION  # untouched
    assert "RECOVERY_MANUAL_REVIEW" in [
        e.event_type for e in store.list_events(run_id="run-1")]


def test_running_step_tool_never_started_is_reset_and_resumed(store):
    """Crash between STEP_STARTED and TOOL_STARTED commits — provably safe."""
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING])
    calls = {"n": 0}
    def _tool(args, ctx):
        calls["n"] += 1
        return {"ok": 1}
    _save_plan(store, "run-1", [_step("s1", StepStatus.RUNNING, tool="github")])
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "PLAN_CREATED", "STEP_STARTED"):
        store.append_event(_event(e, "run-1", step="s1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1", engine=_engine(store, {"github": _tool}))

    assert result.action == "completed"
    assert calls["n"] == 1  # ran exactly once — never duplicated
    assert store.get_plan("plan-1").steps[0].status is StepStatus.COMPLETED
    assert store.get_run("run-1").status is RunStatus.COMPLETED


# ── verification-gated resume ────────────────────────────────────────

def test_verifying_run_completes_when_state_proven(store):
    """VERIFYING + journal proves tool completed + result persisted → complete."""
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING,
                       RunStatus.RUNNING, RunStatus.VERIFYING])
    _save_plan(store, "run-1", [
        _step("s1", StepStatus.COMPLETED, result={"ok": 1}),
    ])
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "STATE_CHANGED", "PLAN_CREATED", "STEP_STARTED",
              "TOOL_STARTED", "TOOL_COMPLETED"):
        store.append_event(_event(e, "run-1", step="s1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1")

    assert result.action == "completed"
    assert store.get_run("run-1").status is RunStatus.COMPLETED
    event_types = [e.event_type for e in store.list_events(run_id="run-1")]
    assert "RECOVERY_VERIFIED" in event_types
    assert event_types[-1] == "RUN_COMPLETED"


def test_verifying_missing_result_goes_manual_review(store):
    """COMPLETED step without persisted result → verification fails → review."""
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING,
                       RunStatus.RUNNING, RunStatus.VERIFYING])
    _save_plan(store, "run-1", [
        _step("s1", StepStatus.COMPLETED, result=None),  # inconsistent row
    ])
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "STATE_CHANGED", "PLAN_CREATED", "STEP_STARTED",
              "TOOL_STARTED", "TOOL_COMPLETED"):
        store.append_event(_event(e, "run-1", step="s1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1")

    assert result.action == "manual_review"
    assert store.get_run("run-1").status is RunStatus.VERIFYING  # untouched
    assert "RECOVERY_MANUAL_REVIEW" in [
        e.event_type for e in store.list_events(run_id="run-1")]


# ── edge cases ───────────────────────────────────────────────────────

def test_needs_planning_without_persisted_plan(store):
    run = _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING])
    store.append_event(_event("RUN_CREATED", "run-1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1", engine=_engine(store))

    assert result.action == "needs_planning"
    assert store.get_run("run-1").status is RunStatus.PLANNING  # untouched
    assert "RECOVERY_WAITING" in [
        e.event_type for e in store.list_events(run_id="run-1")]


def test_engine_must_be_bound_to_same_store(store, tmp_path):
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING])
    _save_plan(store, "run-1", [_step("s1", StepStatus.PENDING)])
    store.append_event(_event("RUN_CREATED", "run-1"))

    other = SQLiteExecutionStore(str(tmp_path / "other.db"))
    try:
        foreign_engine = _engine(other)
        coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
        with pytest.raises(RecoveryErrorBase):
            coordinator.resume("run-1", engine=foreign_engine)
    finally:
        other.close()


def test_terminal_run_is_ignored(store):
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING,
                       RunStatus.RUNNING, RunStatus.VERIFYING])
    run = store.get_run("run-1")
    _run_engine(store).complete_run(run, result={"ok": 1})

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1", engine=_engine(store))

    assert result.action == "ignore"
    assert store.get_run("run-1").status is RunStatus.COMPLETED


def test_resume_audit_trail_order(store):
    """RECOVERY_RESUMED precedes the continued execution; RUN_COMPLETED last."""
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING])
    _save_plan(store, "run-1", [
        _step("s1", StepStatus.COMPLETED, result={"ok": 1}),
        _step("s2", StepStatus.PENDING, tool="llm"),
    ])
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "PLAN_CREATED", "STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED"):
        store.append_event(_event(e, "run-1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    coordinator.resume("run-1", engine=_engine(store))

    types = [e.event_type for e in store.list_events(run_id="run-1")]
    assert types.index("RECOVERY_RESUMED") < types.index("STEP_STARTED", types.index("RECOVERY_RESUMED"))
    assert types[-1] == "RUN_COMPLETED"


def test_plan_failure_during_resume_fails_run(store):
    _build_run(store, [RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING])
    def _boom(args, ctx):
        raise RuntimeError("tool failed")
    _save_plan(store, "run-1", [_step("s1", StepStatus.PENDING, tool="llm")])
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "PLAN_CREATED"):
        store.append_event(_event(e, "run-1"))

    coordinator = ResumeCoordinator(store, run_engine=_run_engine(store))
    result = coordinator.resume("run-1", engine=_engine(store, {"llm": _boom}))

    assert result.action == "failed"
    assert store.get_run("run-1").status is RunStatus.FAILED
    assert store.get_run("run-1").error is not None
