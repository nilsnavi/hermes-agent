"""Recovery classifier tests (Sprint 1.0.4 §classifier)."""

from datetime import datetime, timezone

import pytest

from agent.persistence import SQLiteExecutionStore
from agent.persistence.recovery import RecoveryDisposition
from agent.recovery import RecoveryClassifier
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


def _event(event_type, run_id="r1"):
    return RuntimeEvent(event_type=event_type, run_id=run_id, timestamp=T0, payload={})


def test_classifier_matches_pure_function(store):
    classifier = RecoveryClassifier(store)
    cases = [
        ("r-plan", RunStatus.PLANNING, RecoveryDisposition.SAFE_TO_RESUME),
        ("r-wait", RunStatus.WAITING_APPROVAL, RecoveryDisposition.WAIT_FOR_APPROVAL),
        ("r-verify", RunStatus.VERIFYING, RecoveryDisposition.REQUIRES_VERIFICATION),
        ("r-done", RunStatus.COMPLETED, RecoveryDisposition.TERMINAL),
    ]
    for run_id, status, expected in cases:
        store.save_run(_run(run_id, status))
        assert classifier.classify_run(store.get_run(run_id)) is expected


def test_classifier_uses_journal_order(store):
    """TOOL_STARTED last → MANUAL_REVIEW even though run status is RUNNING."""
    store.save_run(_run("r1", RunStatus.RUNNING))
    for e in ("STEP_STARTED", "TOOL_STARTED"):
        store.append_event(_event(e))
    classifier = RecoveryClassifier(store)
    assert classifier.classify_run(store.get_run("r1")) is RecoveryDisposition.MANUAL_REVIEW


def test_classifier_safe_between_steps(store):
    store.save_run(_run("r1", RunStatus.RUNNING))
    for e in ("STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED"):
        store.append_event(_event(e))
    classifier = RecoveryClassifier(store)
    assert classifier.classify_run(store.get_run("r1")) is RecoveryDisposition.SAFE_TO_RESUME


def test_classifier_events_are_run_scoped(store):
    """Events of OTHER runs must not influence this run's disposition."""
    store.save_run(_run("r1", RunStatus.RUNNING))
    store.save_run(_run("r2", RunStatus.RUNNING))
    store.append_event(_event("TOOL_STARTED", run_id="r2"))  # only r2's journal
    classifier = RecoveryClassifier(store)
    # r1 (empty journal) → REQUIRES_VERIFICATION, NOT manual_review
    assert classifier.classify_run(store.get_run("r1")) is RecoveryDisposition.REQUIRES_VERIFICATION
    # r2 (TOOL_STARTED) → MANUAL_REVIEW — the leaked event did NOT affect r1
    assert classifier.classify_run(store.get_run("r2")) is RecoveryDisposition.MANUAL_REVIEW


def test_disposition_value_serialization():
    assert RecoveryClassifier.disposition_value(RecoveryDisposition.TERMINAL) == "terminal"
