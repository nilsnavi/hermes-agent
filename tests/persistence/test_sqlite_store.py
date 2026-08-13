"""SQLiteExecutionStore CRUD tests (Sprint 1.0.3)."""

from datetime import datetime, timezone

import pytest

from agent.execution.approval import ApprovalRequest, ApprovalStatus
from agent.execution.exceptions import ExecutionErrorBase
from agent.execution.models import (
    ExecutionPlan,
    ExecutionStep,
    PlanStatus,
    StepStatus,
)
from agent.persistence import SQLiteExecutionStore
from agent.persistence.exceptions import ConcurrentUpdateError
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


def _run(run_id="run-1", status=RunStatus.CREATED):
    return AgentRun(
        id=run_id, task_type="report", status=status, model_profile="BALANCED",
        created_at=T0,
    )


def _plan(run_id="run-1"):
    return ExecutionPlan(
        id="plan-1", run_id=run_id, goal="Send daily report",
        status=PlanStatus.CREATED, created_at=T0, metadata={"source": "test"},
    )


def _step(plan_id="plan-1", step_id="step-1", run_id="run-1"):
    return ExecutionStep(
        id=step_id, name="collect_data", description="gather", tool="github",
        arguments={"repo": "navitech"}, status=StepStatus.READY,
    )


def _approval(run_id="run-1"):
    return ApprovalRequest(
        id="approval-1", run_id=run_id, step_id="step-3", reason="send",
        status=ApprovalStatus.PENDING, created_at=T0,
    )


def _event(run_id="run-1", event_type="PLAN_CREATED"):
    return RuntimeEvent(
        event_type=event_type, run_id=run_id, timestamp=T0,
        payload={"plan_id": "plan-1"},
    )


@pytest.fixture
def store(tmp_path):
    s = SQLiteExecutionStore(str(tmp_path / "state.db"))
    yield s
    s.close()


def test_run_roundtrip(store):
    store.save_run(_run())
    loaded = store.get_run("run-1")
    assert loaded.id == "run-1"
    assert loaded.task_type == "report"
    assert loaded.status is RunStatus.CREATED
    assert loaded.model_profile == "BALANCED"
    assert loaded.created_at == T0
    assert loaded.started_at is None
    assert loaded.error is None
    assert loaded.result is None


def test_run_update(store):
    run = _run()
    store.save_run(run)
    run.status = RunStatus.RUNNING
    run.started_at = T0
    store.update_run(run)
    loaded = store.get_run("run-1")
    assert loaded.status is RunStatus.RUNNING
    assert loaded.started_at == T0


def test_run_version_conflict(store):
    store.save_run(_run())
    run = _run(status=RunStatus.CLASSIFYING)
    store.update_run(run, expected_version=1)  # v1 → v2
    with pytest.raises(ConcurrentUpdateError):
        store.update_run(run, expected_version=1)  # stale — already v2


def test_run_missing_raises(store):
    with pytest.raises(ExecutionErrorBase):
        store.get_run("nope")


def test_run_unicode_roundtrip(store):
    run = _run(run_id="run-юникод")
    run.result = {"привет": "мир", "emoji": "🚀"}
    store.save_run(run)
    loaded = store.get_run("run-юникод")
    assert loaded.result == {"привет": "мир", "emoji": "🚀"}


def test_run_none_and_empty_roundtrip(store):
    run = _run()
    run.result = {}
    run.context = None
    store.save_run(run)
    loaded = store.get_run("run-1")
    assert loaded.result == {}
    assert loaded.context is None


def test_plan_roundtrip(store):
    store.save_run(_run())
    plan = _plan()
    store.save_plan(plan)
    loaded = store.get_plan("plan-1")
    assert loaded.id == "plan-1"
    assert loaded.run_id == "run-1"
    assert loaded.goal == "Send daily report"
    assert loaded.status is PlanStatus.CREATED
    assert loaded.created_at == T0
    assert loaded.metadata == {"source": "test"}


def test_plan_with_steps_roundtrip(store):
    store.save_run(_run())
    plan = _plan()
    store.save_plan(plan)
    store.save_step("plan-1", _step(step_id="step-1"))
    store.save_step("plan-1", _step(step_id="step-2"))
    loaded = store.get_plan("plan-1")
    assert [s.id for s in loaded.steps] == ["step-1", "step-2"]


def test_plan_requires_run_row(store):
    with pytest.raises(Exception):  # FK violation → sqlite3.IntegrityError
        store.save_plan(_plan())


def test_step_roundtrip(store):
    store.save_run(_run())
    store.save_plan(_plan())
    store.save_step("plan-1", _step())
    loaded = store.get_step("plan-1", "step-1")
    assert loaded.name == "collect_data"
    assert loaded.tool == "github"
    assert loaded.arguments == {"repo": "navitech"}
    assert loaded.status is StepStatus.READY


def test_step_update_version_guard(store):
    store.save_run(_run())
    store.save_plan(_plan())
    step = _step()
    store.save_step("plan-1", step)
    step.status = StepStatus.COMPLETED
    store.update_step("plan-1", step, expected_version=1)
    with pytest.raises(ConcurrentUpdateError):
        store.update_step("plan-1", step, expected_version=1)
    assert store.get_step("plan-1", "step-1").status is StepStatus.COMPLETED


def test_approval_roundtrip(store):
    store.save_run(_run())
    store.save_approval(_approval())
    loaded = store.get_approval("approval-1")
    assert loaded.step_id == "step-3"
    assert loaded.status is ApprovalStatus.PENDING
    assert loaded.reason == "send"
    assert loaded.created_at == T0


def test_approval_update_and_double_decision_guard(store):
    store.save_run(_run())
    approval = _approval()
    store.save_approval(approval)
    approval.status = ApprovalStatus.APPROVED
    store.update_approval(approval, expected_version=1)
    with pytest.raises(ConcurrentUpdateError):
        store.update_approval(approval, expected_version=1)
    assert store.get_approval("approval-1").status is ApprovalStatus.APPROVED


def test_event_append_and_list(store):
    store.append_event(_event())
    store.append_event(_event(event_type="STEP_STARTED"))
    events = store.list_events(run_id="run-1")
    assert [e.event_type for e in events] == ["PLAN_CREATED", "STEP_STARTED"]
    assert all(e.run_id == "run-1" for e in events)
    assert events[0].timestamp == T0
    assert events[0].payload == {"plan_id": "plan-1"}


def test_event_filter_by_type(store):
    store.append_event(_event())
    store.append_event(_event(event_type="STEP_STARTED"))
    only = store.list_events(run_id="run-1", event_type="PLAN_CREATED")
    assert len(only) == 1
    assert only[0].event_type == "PLAN_CREATED"


def test_event_ordering_by_id(store):
    # Same timestamp for all — ordering must come from the journal id.
    for i in range(5):
        store.append_event(_event(event_type=f"E{i}"))
    events = store.list_events(run_id="run-1")
    assert [e.event_type for e in events] == [f"E{i}" for i in range(5)]


def test_list_incomplete_runs(store):
    store.save_run(_run(run_id="r1", status=RunStatus.RUNNING))
    store.save_run(_run(run_id="r2", status=RunStatus.COMPLETED))
    store.save_run(_run(run_id="r3", status=RunStatus.WAITING_APPROVAL))
    incomplete = [r.id for r in store.list_incomplete_runs()]
    assert incomplete == ["r1", "r3"]


def test_restart_reopen_roundtrip(tmp_path):
    path = str(tmp_path / "state.db")
    s1 = SQLiteExecutionStore(path)
    s1.save_run(_run())
    plan = _plan()
    s1.save_plan(plan)
    s1.save_step("plan-1", _step())
    s1.save_approval(_approval())
    s1.append_event(_event())
    s1.close()

    # "Process B" — fresh store on the same file.
    s2 = SQLiteExecutionStore(path)
    run = s2.get_run("run-1")
    assert run.id == "run-1" and run.status is RunStatus.CREATED
    loaded_plan = s2.get_plan("plan-1")
    assert loaded_plan.goal == "Send daily report"
    assert [s.id for s in loaded_plan.steps] == ["step-1"]
    assert s2.get_approval("approval-1").status is ApprovalStatus.PENDING
    assert [e.event_type for e in s2.list_events(run_id="run-1")] == ["PLAN_CREATED"]
    s2.close()


def test_performance_smoke(tmp_path):
    """§39 — create/update/append/load must be milliseconds, not seconds."""
    import time

    store = SQLiteExecutionStore(str(tmp_path / "perf.db"))
    run = _run()
    store.save_run(run)
    plan = _plan()
    store.save_plan(plan)
    for i in range(10):
        store.save_step("plan-1", _step(step_id=f"step-{i}"))
    started = time.perf_counter()
    store.save_run(run)
    run.status = RunStatus.RUNNING
    store.update_run(run)
    for i in range(50):
        store.append_event(_event(event_type=f"E{i}"))
    store.get_run("run-1")
    store.get_plan("plan-1")
    store.list_events(run_id="run-1")
    elapsed = time.perf_counter() - started
    store.close()
    assert elapsed < 2.0, f"perf smoke too slow: {elapsed:.2f}s"
