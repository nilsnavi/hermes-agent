"""Manual review queue tests (Sprint 1.0.4)."""

from datetime import datetime, timezone

import pytest

from agent.persistence import SQLiteExecutionStore
from agent.recovery import ManualReviewQueue
from agent.recovery.exceptions import RecoveryErrorBase

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = SQLiteExecutionStore(str(tmp_path / "state.db"))
    yield s
    s.close()


def test_add_and_pending(store):
    queue = ManualReviewQueue(store, clock=lambda: T0)
    item = queue.add("run-1", "unknown tool outcome")
    assert item.run_id == "run-1"
    assert item.resolved is False
    assert [i.run_id for i in queue.pending()] == ["run-1"]


def test_add_is_idempotent_per_run(store):
    queue = ManualReviewQueue(store, clock=lambda: T0)
    queue.add("run-1", "first")
    queue.add("run-1", "second")
    assert len(queue.pending()) == 1
    assert queue.pending()[0].reason == "first"


def test_resolve_records_decision(store):
    queue = ManualReviewQueue(store, clock=lambda: T0)
    queue.add("run-1", "unknown")
    resolved = queue.resolve("run-1", decision="verified_externally", note="checked")
    assert resolved.resolved is True
    assert resolved.decision == "verified_externally"
    assert queue.pending() == []
    assert "RECOVERY_REVIEWED" in [e.event_type for e in store.list_events(run_id="run-1")]


def test_resolve_twice_raises(store):
    queue = ManualReviewQueue(store, clock=lambda: T0)
    queue.add("run-1", "unknown")
    queue.resolve("run-1", decision="cancelled")
    with pytest.raises(RecoveryErrorBase):
        queue.resolve("run-1", decision="retry")


def test_get_unknown_raises(store):
    queue = ManualReviewQueue(store, clock=lambda: T0)
    with pytest.raises(RecoveryErrorBase):
        queue.get("ghost")


def test_add_writes_audit_event(store):
    queue = ManualReviewQueue(store, clock=lambda: T0)
    queue.add("run-1", "ambiguous")
    events = store.list_events(run_id="run-1")
    assert events[0].event_type == "RECOVERY_MANUAL_REVIEW"
    assert events[0].payload["reason"] == "ambiguous"


def test_review_does_not_transition_run(store):
    """Resolving a review NEVER moves the run — operator decision only."""
    from agent.runtime.models import AgentRun
    from agent.runtime.states import RunStatus

    store.save_run(AgentRun(id="run-1", task_type="t", status=RunStatus.TOOL_EXECUTION,
                            model_profile="BALANCED", created_at=T0))
    queue = ManualReviewQueue(store, clock=lambda: T0)
    queue.add("run-1", "unknown")
    queue.resolve("run-1", decision="cancelled")
    assert store.get_run("run-1").status is RunStatus.TOOL_EXECUTION
