"""Process-restart + crash simulation tests (Sprint 1.0.3 §37 / §38).

Uses the REAL RunEngine + ExecutionEngine wired to SQLiteExecutionStore:
the full production-shaped path, not hand-written rows.
"""

from datetime import datetime, timezone

import pytest

from agent.execution import ExecutionEngine, ExecutionPlanner, ToolRegistry, ToolRuntime
from agent.execution.events import TOOL_COMPLETED, TOOL_STARTED
from agent.execution.models import PlanStatus, StepStatus
from agent.persistence import SQLiteExecutionStore
from agent.persistence.recovery import RecoveryDisposition, classify
from agent.runtime.context import TaskContext
from agent.runtime.run_engine import RunEngine
from agent.runtime.states import RunStatus

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


def _registry(handlers=None):
    reg = ToolRegistry()
    reg.register("github", lambda a, c: {"commits": 1})
    reg.register("llm", lambda a, c: {"report": "ok"})
    reg.register("telegram", lambda a, c: {"sent": True})
    for name, handler in (handlers or {}).items():
        reg.register(name, handler)
    return reg


def _ctx():
    return TaskContext(goal="Send daily report",
                       allowed_tools=["github", "llm", "telegram"])


def test_restart_recovery_exact_state(tmp_path):
    """§37 — Process A builds state up to an approval gate; Process B reopens
    and sees the EXACT same state. No resume happens."""
    path = str(tmp_path / "state.db")

    # ── Process A ────────────────────────────────────────────────────
    store_a = SQLiteExecutionStore(path)
    run_engine = RunEngine(clock=lambda: T0, store=store_a)
    run = run_engine.create_run("report", "BALANCED", run_id="run-1")
    run_engine.transition(run, RunStatus.CLASSIFYING)
    run_engine.transition(run, RunStatus.PLANNING)
    run_engine.transition(run, RunStatus.RUNNING)

    exec_engine = ExecutionEngine(
        ToolRuntime(_registry(), timeout=5), store=store_a,
        clock=lambda: T0,
    )
    plan = ExecutionPlanner(clock=lambda: T0).create_plan(
        "run-1", _ctx(),
        [
            {"name": "collect_data", "tool": "github"},
            {"name": "generate_report", "tool": "llm"},
            {"name": "send_message", "tool": "telegram", "requires_approval": True},
        ],
        plan_id="plan-1",
    )
    exec_engine.execute_plan(plan)  # pauses at step-3 (approval gate)
    assert plan.status is PlanStatus.RUNNING
    assert plan.steps[2].status is StepStatus.WAITING_APPROVAL
    store_a.close()

    # ── Process B — fresh store on the same file ─────────────────────
    store_b = SQLiteExecutionStore(path)
    loaded_run = store_b.get_run("run-1")
    assert loaded_run.status is RunStatus.RUNNING

    loaded_plan = store_b.get_plan("plan-1")
    assert loaded_plan.goal == "Send daily report"
    assert [s.status for s in loaded_plan.steps] == [
        StepStatus.COMPLETED, StepStatus.COMPLETED, StepStatus.WAITING_APPROVAL,
    ]
    assert loaded_plan.steps[0].result is not None  # step result survived

    approvals = store_b.list_approvals(run_id="run-1")
    assert len(approvals) == 1
    assert approvals[0].step_id == "step-3"

    event_types = [e.event_type for e in store_b.list_events(run_id="run-1")]
    assert event_types[-1] == "STEP_WAITING_APPROVAL"
    # Exact journal order — unambiguous by journal id, not just timestamp.
    assert event_types == [
        "RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
        "PLAN_CREATED",
        "STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED",
        "STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED",
        "STEP_STARTED", "STEP_WAITING_APPROVAL",
    ]
    store_b.close()


def test_crash_during_tool_execution_no_auto_retry(tmp_path):
    """§38 — TOOL_STARTED persisted, process dies mid-tool. Recovery MUST
    classify MANUAL_REVIEW and must NOT run the tool again."""
    path = str(tmp_path / "state.db")
    calls = {"n": 0}

    def _exploding_tool(args, ctx):
        calls["n"] += 1
        raise SystemExit("process died mid-tool")  # simulated crash

    store = SQLiteExecutionStore(path)
    run_engine = RunEngine(clock=lambda: T0, store=store)
    run = run_engine.create_run("report", "BALANCED", run_id="run-1")
    for target in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING):
        run_engine.transition(run, target)
    run_engine.transition(run, RunStatus.TOOL_EXECUTION)

    exec_engine = ExecutionEngine(
        ToolRuntime(_registry(handlers={"github": _exploding_tool}), timeout=5),
        store=store, clock=lambda: T0,
    )
    plan = ExecutionPlanner(clock=lambda: T0).create_plan(
        "run-1", _ctx(),
        [{"name": "collect_data", "tool": "github"}],
        plan_id="plan-1",
    )
    with pytest.raises(SystemExit):
        exec_engine.execute_plan(plan)  # engine dies inside the tool call
    store.close()

    # ── Recovery side: reopen and classify ───────────────────────────
    store2 = SQLiteExecutionStore(path)
    loaded_run = store2.get_run("run-1")
    events = [e.event_type for e in store2.list_events(run_id="run-1")]
    assert TOOL_STARTED in events
    assert TOOL_COMPLETED not in events  # journal proves the crash point

    disposition = classify(loaded_run.status, events)
    assert disposition is RecoveryDisposition.MANUAL_REVIEW
    assert calls["n"] == 1  # the tool ran exactly once — NO automatic retry
    store2.close()


def test_runengine_persists_every_transition(tmp_path):
    path = str(tmp_path / "state.db")
    store = SQLiteExecutionStore(path)
    run_engine = RunEngine(clock=lambda: T0, store=store)
    run = run_engine.create_run("report", "BALANCED", run_id="run-1")
    for target in (RunStatus.CLASSIFYING, RunStatus.PLANNING,
                   RunStatus.WAITING_APPROVAL, RunStatus.APPROVED, RunStatus.RUNNING,
                   RunStatus.TOOL_EXECUTION, RunStatus.VERIFYING):
        run_engine.transition(run, target)
    run_engine.complete_run(run, result={"ok": True})

    store2 = SQLiteExecutionStore(path)
    loaded = store2.get_run("run-1")
    assert loaded.status is RunStatus.COMPLETED
    assert loaded.result == {"ok": True}
    assert loaded.completed_at is not None
    events = [e.event_type for e in store2.list_events(run_id="run-1")]
    assert events[0] == "RUN_CREATED"
    assert events[-1] == "RUN_COMPLETED"
    store2.close()
