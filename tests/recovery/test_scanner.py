"""Recovery scanner tests (Sprint 1.0.4)."""

from datetime import datetime, timezone

import pytest

from agent.execution.events import TOOL_STARTED
from agent.persistence import SQLiteExecutionStore
from agent.recovery import RecoveryScanner
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = SQLiteExecutionStore(str(tmp_path / "state.db"))
    yield s
    s.close()


def _run(run_id, status):
    return AgentRun(id=run_id, task_type="t", status=status,
                    model_profile="BALANCED", created_at=T0)


def test_scan_finds_and_buckets_incomplete_runs(store):
    store.save_run(_run("r-running", RunStatus.RUNNING))
    # a completed tool cycle in the journal → SAFE_TO_RESUME
    store.append_event(RuntimeEvent(event_type="TOOL_COMPLETED", run_id="r-running",
                                    timestamp=T0, payload={}))
    store.save_run(_run("r-wait", RunStatus.WAITING_APPROVAL))
    store.save_run(_run("r-plan", RunStatus.PLANNING))
    store.save_run(_run("r-tool", RunStatus.TOOL_EXECUTION))
    store.save_run(_run("r-done", RunStatus.COMPLETED))  # excluded — terminal

    results = RecoveryScanner(store, clock=lambda: T0).scan(audit=False)

    by_id = {r.run_id: r for r in results}
    assert set(by_id) == {"r-running", "r-wait", "r-plan", "r-tool"}
    assert by_id["r-running"].action == "resume"
    assert by_id["r-wait"].action == "wait"
    assert by_id["r-plan"].action == "resume"
    assert by_id["r-tool"].action == "manual_review"
    assert by_id["r-wait"].disposition == "wait_for_approval"


def test_scan_writes_audit_events(store):
    store.save_run(_run("r1", RunStatus.RUNNING))
    store.append_event(RuntimeEvent(event_type=TOOL_STARTED, run_id="r1",
                                    timestamp=T0, payload={"step": "s1"}))

    RecoveryScanner(store, clock=lambda: T0).scan(audit=True)

    types = [e.event_type for e in store.list_events(run_id="r1")]
    assert "RECOVERY_SCANNED" in types
    assert "RECOVERY_CLASSIFIED" in types
    # audit events are appended AFTER the original journal entries
    assert types.index("RECOVERY_SCANNED") > types.index(TOOL_STARTED)


def test_scan_does_not_execute_anything(store):
    """Scan is read-only: run/step state must be byte-identical."""
    store.save_run(_run("r1", RunStatus.RUNNING))
    before = store.get_run("r1").status
    RecoveryScanner(store, clock=lambda: T0).scan(audit=True)
    assert store.get_run("r1").status is before
    assert store.get_run("r1").status is RunStatus.RUNNING


def test_scan_empty_store(store):
    assert RecoveryScanner(store, clock=lambda: T0).scan() == []
