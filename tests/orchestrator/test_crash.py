"""Crash-safety tests (Sprint 1.0.5 §51/§52) — the no-auto-retry contract."""

from agent.execution.events import TOOL_COMPLETED, TOOL_STARTED
from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from agent.orchestrator import ExecutionPolicy, StopReason
from agent.persistence import SQLiteExecutionStore
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.run_engine import RunEngine
from agent.runtime.states import RunStatus

from tests.orchestrator.conftest import T0, make_orchestrator, spec


def _ctx(**kw):
    from agent.runtime.context import TaskContext

    kwargs = dict(goal="task", allowed_tools=["search", "fetch", "save_draft"])
    kwargs.update(kw)
    return TaskContext(**kwargs)  # type: ignore[arg-type]


def _build_crash_state(path, step_status, events, result=None, registry=None):
    """Manually build a run in the state a crash would leave behind."""
    from tests.orchestrator.conftest import _make_registry

    store = SQLiteExecutionStore(path)
    run_engine = RunEngine(clock=lambda: T0, store=store)
    run = run_engine.create_run("t", "BALANCED", run_id="run-1")
    for target in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING):
        run_engine.transition(run, target)
    plan = ExecutionPlan(id="plan-1", run_id="run-1", goal="g",
                         status=PlanStatus.RUNNING, created_at=T0)
    store.save_plan(plan)
    store.save_step("plan-1", ExecutionStep(
        id="s1", name="s1", description="", tool="search",
        status=step_status, result=result,
    ))
    for e in events:
        store.append_event(RuntimeEvent(event_type=e, run_id="run-1",
                                        timestamp=T0, payload={"step": "s1"}))
    store.close()
    return store


def test_crash_mid_tool_no_automatic_retry(tmp_path, registry, clock):
    """§51 MANDATORY — TOOL_STARTED persisted, process died: MANUAL_REVIEW.

    The tool must NEVER be called again (call count stays 1 from before)."""
    path = str(tmp_path / "c.db")
    calls = {"n": 0}

    def _tool(args, ctx):
        calls["n"] += 1
        return {"hits": 1}
    registry.register("search", _tool)

    _build_crash_state(path, StepStatus.RUNNING,
                       ["STEP_STARTED", TOOL_STARTED])

    store_b = SQLiteExecutionStore(path)
    orch = make_orchestrator(store_b, registry, clock)
    result = orch.resume("run-1")

    assert result.stop_reason is StopReason.MANUAL_REVIEW_REQUIRED
    assert calls["n"] == 0  # never called again after the crash
    assert store_b.get_run("run-1").status is RunStatus.RUNNING
    store_b.close()


def test_stored_tool_completed_reused_no_execution(tmp_path, registry, clock):
    """§52 — TOOL_COMPLETED + result persisted: reuse, do NOT re-run."""
    path = str(tmp_path / "c.db")
    calls = {"n": 0}

    def _tool(args, ctx):
        calls["n"] += 1
        return {"hits": 1}
    registry.register("search", _tool)

    stored = {"status": "success", "output": {"hits": 1},
              "execution_time": 0.1, "error": None}
    _build_crash_state(path, StepStatus.PENDING,
                       ["STEP_STARTED", TOOL_STARTED, TOOL_COMPLETED],
                       result=stored)

    store_b = SQLiteExecutionStore(path)
    orch = make_orchestrator(store_b, registry, clock)
    result = orch.resume("run-1")

    assert result.stop_reason is StopReason.COMPLETED
    assert calls["n"] == 0  # result reused — tool never re-run
    assert store_b.get_run("run-1").result == {"s1": stored}
    types = [e.event_type for e in store_b.list_events(run_id="run-1")]
    assert "DUPLICATE_ACTION_DETECTED" in types
    store_b.close()


def test_crash_after_step_committed_continues(tmp_path, registry, clock):
    """Completed step survives; the NEXT pending step executes once."""
    path = str(tmp_path / "c.db")
    calls = {"fetch": 0}

    def _fetch(args, ctx):
        calls["fetch"] += 1
        return {"rows": 2}
    registry.register("fetch", _fetch)

    store = SQLiteExecutionStore(path)
    run_engine = RunEngine(clock=lambda: T0, store=store)
    run = run_engine.create_run("t", "BALANCED", run_id="run-1")
    for target in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING):
        run_engine.transition(run, target)
    plan = ExecutionPlan(id="plan-1", run_id="run-1", goal="g",
                         status=PlanStatus.RUNNING, created_at=T0)
    store.save_plan(plan)
    store.save_step("plan-1", ExecutionStep(
        id="s1", name="s1", description="", tool="search",
        status=StepStatus.COMPLETED,
        result={"status": "success", "output": {"hits": 1}, "execution_time": 0.1, "error": None},
    ))
    store.save_step("plan-1", ExecutionStep(
        id="s2", name="s2", description="", tool="fetch", status=StepStatus.PENDING,
    ))
    for e in ("RUN_CREATED", "STATE_CHANGED", "STATE_CHANGED", "STATE_CHANGED",
              "PLAN_CREATED", "STEP_STARTED", TOOL_STARTED, TOOL_COMPLETED):
        store.append_event(RuntimeEvent(event_type=e, run_id="run-1",
                                        timestamp=T0,
                                        payload={"step": "s1"} if "STEP" in e or "TOOL" in e else {}))
    store.close()

    store_b = SQLiteExecutionStore(path)
    orch = make_orchestrator(store_b, registry, clock)
    result = orch.resume("run-1")

    assert result.stop_reason is StopReason.COMPLETED
    assert calls["fetch"] == 1  # only the pending step ran
    assert result.tool_calls == 2  # 1 completed (s1) + 1 new (s2)
    store_b.close()


def test_running_step_without_tool_started_is_reset(store, registry, clock):
    """Crash between STEP_STARTED and TOOL_STARTED: provably safe to retry."""
    from agent.runtime.events import RuntimeEvent

    calls = {"search": 0}

    def _tool(args, ctx):
        calls["search"] += 1
        return {"hits": 1}
    registry.register("search", _tool)

    run_engine = RunEngine(clock=lambda: T0, store=store)
    run = run_engine.create_run("t", "BALANCED", run_id="run-1")
    for target in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING):
        run_engine.transition(run, target)
    plan = ExecutionPlan(id="plan-1", run_id="run-1", goal="g",
                         status=PlanStatus.RUNNING, created_at=T0)
    store.save_plan(plan)
    store.save_step("plan-1", ExecutionStep(
        id="s1", name="s1", description="", tool="search", status=StepStatus.RUNNING,
    ))
    store.append_event(RuntimeEvent(event_type="STEP_STARTED", run_id="run-1",
                                    timestamp=T0, payload={"step": "s1"}))

    orch = make_orchestrator(store, registry, clock)
    result = orch.resume("run-1")

    assert result.stop_reason is StopReason.COMPLETED
    assert calls["search"] == 1  # ran exactly once — never duplicated
    store.close()
