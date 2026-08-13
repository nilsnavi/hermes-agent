"""Optimistic-concurrency tests (Sprint 1.0.3 §14 / §16 / §35)."""

from datetime import datetime, timezone

import pytest

from agent.execution.approval import ApprovalRequest, ApprovalStatus
from agent.execution.exceptions import ExecutionErrorBase
from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from agent.persistence import SQLiteExecutionStore
from agent.persistence.exceptions import ConcurrentUpdateError
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = SQLiteExecutionStore(str(tmp_path / "state.db"))
    yield s
    s.close()


def test_two_updates_same_version_one_conflicts(store):
    run = AgentRun(id="r1", task_type="t", status=RunStatus.CREATED,
                   model_profile="BALANCED", created_at=T0)
    store.save_run(run)
    store.update_run(run, expected_version=1)  # worker A wins
    with pytest.raises(ConcurrentUpdateError):
        store.update_run(run, expected_version=1)  # worker B (stale) loses


def test_double_approval_persisted_guard(store):
    store.save_run(AgentRun(id="r1", task_type="t", status=RunStatus.RUNNING,
                            model_profile="BALANCED", created_at=T0))
    approval = ApprovalRequest(id="a1", run_id="r1", step_id="s1",
                               status=ApprovalStatus.PENDING, created_at=T0)
    store.save_approval(approval)
    approval.status = ApprovalStatus.APPROVED
    store.update_approval(approval, expected_version=1)
    with pytest.raises(ConcurrentUpdateError):
        store.update_approval(approval, expected_version=1)
    assert store.get_approval("a1").status is ApprovalStatus.APPROVED


def test_duplicate_run_creation_is_idempotent(store):
    """save_run twice (retry after crash) must NOT silently duplicate."""
    run = AgentRun(id="r1", task_type="t", status=RunStatus.CREATED,
                   model_profile="BALANCED", created_at=T0)
    store.save_run(run)
    run.status = RunStatus.RUNNING
    store.save_run(run)  # retry of the same create
    loaded = store.get_run("r1")
    assert loaded.status is RunStatus.RUNNING  # last-write-wins, no dup row
    assert len(store.list_incomplete_runs()) == 1


def test_multiple_event_appends_ordered(store):
    for i in range(20):
        store.append_event(RuntimeEvent(event_type=f"E{i}", run_id="r1",
                                        timestamp=T0, payload={"i": i}))
    events = store.list_events(run_id="r1")
    assert len(events) == 20
    assert [e.payload["i"] for e in events] == list(range(20))


def test_two_stores_same_file_sequential(store, tmp_path):
    """Two store instances on one file: sequential writes both succeed."""
    other = SQLiteExecutionStore(str(tmp_path / "state.db"))
    run = AgentRun(id="r2", task_type="t", status=RunStatus.CREATED,
                   model_profile="BALANCED", created_at=T0)
    store.save_run(run)
    other.save_run(run)
    run.status = RunStatus.RUNNING
    store.update_run(run)  # auto-read path
    other.update_run(run)
    assert other.get_run("r2").status is RunStatus.RUNNING
    other.close()


def test_update_missing_row_raises(store):
    run = AgentRun(id="ghost", task_type="t", status=RunStatus.CREATED,
                   model_profile="BALANCED", created_at=T0)
    with pytest.raises(ExecutionErrorBase):
        store.update_run(run)
