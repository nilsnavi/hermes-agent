"""RecoveryEngine integration tests (Sprint 1.0.4).

Full process-restart lifecycle: Process A builds durable state with the
REAL RunEngine + ExecutionEngine, dies; Process B opens the same SQLite
file and runs RecoveryEngine.scan / recover / approve.
"""

from datetime import datetime, timezone

import pytest

from agent.execution import ExecutionEngine, ExecutionPlanner, ToolRegistry, ToolRuntime
from agent.execution.approval import ApprovalStatus
from agent.execution.events import TOOL_STARTED
from agent.execution.models import PlanStatus, StepStatus
from agent.persistence import SQLiteExecutionStore
from agent.recovery import RecoveryEngine
from agent.recovery.exceptions import RecoveryErrorBase
from agent.runtime.context import TaskContext
from agent.runtime.events import RuntimeEvent
from agent.runtime.run_engine import RunEngine
from agent.runtime.states import RunStatus

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
CLOCK = lambda: T0  # noqa: E731


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


def _ctx():
    return TaskContext(goal="Send daily report",
                       allowed_tools=["github", "llm", "telegram"])


def _process_a_state(path, crash_at_gate=True):
    """Build a run paused at the telegram approval gate; returns run id."""
    store = SQLiteExecutionStore(path)
    run_engine = _run_engine(store)
    run = run_engine.create_run("report", "BALANCED", run_id="run-1")
    for target in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING):
        run_engine.transition(run, target)
    exec_engine = _engine(store)
    plan = ExecutionPlanner(clock=CLOCK).create_plan(
        "run-1", _ctx(),
        [
            {"name": "collect_data", "tool": "github"},
            {"name": "generate_report", "tool": "llm"},
            {"name": "send_message", "tool": "telegram", "requires_approval": True},
        ],
        plan_id="plan-1",
    )
    exec_engine.execute_plan(plan)  # pauses at step-3
    store.close()
    return "run-1"


def test_recover_resumes_and_buckets_multiple_runs(tmp_path):
    """Three crashed runs: resume one, wait on one, manual-review one."""
    path = str(tmp_path / "state.db")

    # run-1: crashed between steps → SAFE_TO_RESUME
    store = SQLiteExecutionStore(path)
    run_engine = _run_engine(store)
    run = run_engine.create_run("report", "BALANCED", run_id="run-1")
    for t in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING):
        run_engine.transition(run, t)
    from agent.execution.models import ExecutionPlan, ExecutionStep
    plan = ExecutionPlan(id="plan-1", run_id="run-1", goal="g",
                         status=PlanStatus.RUNNING, created_at=T0)
    store.save_plan(plan)
    store.save_step("plan-1", ExecutionStep(
        id="s1", name="n", description="", tool="github",
        status=StepStatus.COMPLETED, result={"output": {"ok": 1}},
    ))
    store.save_step("plan-1", ExecutionStep(
        id="s2", name="n", description="", tool="llm", status=StepStatus.PENDING,
    ))
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "PLAN_CREATED", "STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED"):
        store.append_event(RuntimeEvent(event_type=e, run_id="run-1",
                                        timestamp=T0, payload={"step": "s1"} if "TOOL" in e or "STEP" in e else {}))

    # run-2: waiting at an approval gate
    run2 = run_engine.create_run("report", "BALANCED", run_id="run-2")
    for t in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.WAITING_APPROVAL):
        run_engine.transition(run2, t)
    store.append_event(RuntimeEvent(event_type="STEP_WAITING_APPROVAL", run_id="run-2",
                                    timestamp=T0, payload={"step": "s1"}))

    # run-3: died mid-tool
    run3 = run_engine.create_run("report", "BALANCED", run_id="run-3")
    for t in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING,
              RunStatus.TOOL_EXECUTION):
        run_engine.transition(run3, t)
    store.append_event(RuntimeEvent(event_type=TOOL_STARTED, run_id="run-3",
                                    timestamp=T0, payload={"step": "s1"}))
    store.close()

    # ── Process B: recovery ──────────────────────────────────────────
    store2 = SQLiteExecutionStore(path)
    engine = RecoveryEngine(store2, run_engine=_run_engine(store2), clock=CLOCK)
    calls = {"llm": 0}
    def _llm(args, ctx):
        calls["llm"] += 1
        return {"report": "ok"}
    report = engine.recover(engine_factory=lambda: _engine(store2, {"llm": _llm}))

    assert report.counts()["scanned"] == 3
    assert report.counts()["resumed"] == 1
    assert report.counts()["waiting"] == 1
    assert report.counts()["manual_review"] == 1

    assert store2.get_run("run-1").status is RunStatus.COMPLETED
    assert store2.get_run("run-2").status is RunStatus.WAITING_APPROVAL  # untouched
    assert store2.get_run("run-3").status is RunStatus.TOOL_EXECUTION     # untouched
    assert calls["llm"] == 1  # exactly one resumed step executed
    assert [i.run_id for i in engine.manual_review.pending()] == ["run-3"]
    store2.close()


def test_scan_alone_executes_nothing(tmp_path):
    path = str(tmp_path / "state.db")
    _process_a_state(path)

    store = SQLiteExecutionStore(path)
    engine = RecoveryEngine(store, run_engine=_run_engine(store), clock=CLOCK)
    report = engine.scan()  # NO engine factory — nothing may execute

    assert report.counts()["waiting"] == 1
    assert store.get_run("run-1").status is RunStatus.RUNNING  # untouched
    store2 = SQLiteExecutionStore(path)
    assert store2.list_approvals(run_id="run-1")[0].status is ApprovalStatus.PENDING
    store.close()
    store2.close()


def test_full_restart_lifecycle_approve_then_resume(tmp_path):
    """Crash at gate → Process B: wait → approve persisted approval → done.

    The approval decision is made against the DURABLE row (the fresh
    engine's in-memory ApprovalManager knows nothing about it), and the
    granted gate is seeded so no second approval request is created.
    """
    path = str(tmp_path / "state.db")
    _process_a_state(path)

    store = SQLiteExecutionStore(path)
    engine = RecoveryEngine(store, run_engine=_run_engine(store), clock=CLOCK)

    # 1. Scan → waiting (no duplicate approval request)
    report = engine.scan()
    assert report.counts()["waiting"] == 1
    approval = store.list_approvals(run_id="run-1")[0]
    assert approval.status is ApprovalStatus.PENDING
    assert len(store.list_approvals(run_id="run-1")) == 1

    # 2. Approve the persisted approval → resumes and completes the run
    result = engine.approve("run-1", approval.id,
                            engine=_engine(store))
    assert result.action == "completed"
    assert store.get_run("run-1").status is RunStatus.COMPLETED
    assert store.get_plan("plan-1").status is PlanStatus.COMPLETED

    # 3. No duplicate approval was ever created
    approvals = store.list_approvals(run_id="run-1")
    assert len(approvals) == 1
    assert approvals[0].status is ApprovalStatus.APPROVED

    # 4. Audit trail: recovery events in the durable journal
    types = [e.event_type for e in store.list_events(run_id="run-1")]
    assert "RECOVERY_SCANNED" in types
    assert "RECOVERY_CLASSIFIED" in types
    assert "STEP_APPROVED" in types
    assert types[-1] == "RUN_COMPLETED"
    store.close()


def test_approve_twice_is_refused(tmp_path):
    path = str(tmp_path / "state.db")
    _process_a_state(path)

    store = SQLiteExecutionStore(path)
    engine = RecoveryEngine(store, run_engine=_run_engine(store), clock=CLOCK)
    approval = store.list_approvals(run_id="run-1")[0]
    engine.approve("run-1", approval.id, engine=_engine(store))
    with pytest.raises(RecoveryErrorBase):
        engine.approve("run-1", approval.id, engine=_engine(store))
    store.close()


def test_recover_without_factory_reports_only(tmp_path):
    path = str(tmp_path / "state.db")
    _process_a_state(path)

    store = SQLiteExecutionStore(path)
    engine = RecoveryEngine(store, run_engine=_run_engine(store), clock=CLOCK)
    report = engine.recover()  # no factory → scan-only

    assert report.counts()["resumed"] == 0
    assert report.counts()["waiting"] == 1
    assert store.get_run("run-1").status is RunStatus.RUNNING
    store.close()
