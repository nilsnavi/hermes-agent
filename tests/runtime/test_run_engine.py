"""RunEngine tests (Sprint 1.0.1): lifecycle + event trail."""

from datetime import datetime, timedelta, timezone

import pytest

from agent.runtime.events import (
    RUN_COMPLETED,
    RUN_CREATED,
    RUN_FAILED,
    STATE_CHANGED,
)
from agent.runtime.exceptions import InvalidStateTransition
from agent.runtime.run_engine import RunEngine
from agent.runtime.states import RunStatus


class _Clock:
    def __init__(self):
        self.now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def test_create_run():
    engine = RunEngine()
    run = engine.create_run(task_type="report", model_profile="BALANCED")
    assert run.status is RunStatus.CREATED
    assert run.task_type == "report"
    assert run.model_profile == "BALANCED"
    assert run.id.startswith("run_")
    assert run.created_at is not None
    assert run.started_at is None
    assert run.completed_at is None
    assert run.error is None
    assert run.result is None
    assert len(engine.events) == 1
    assert engine.events[0].event_type == RUN_CREATED
    assert engine.events[0].run_id == run.id


def test_create_run_explicit_id_is_preserved():
    run = RunEngine().create_run("report", "FAST", run_id="run-42")
    assert run.id == "run-42"


def test_start_run_transitions_to_classifying():
    engine = RunEngine()
    run = engine.create_run("report", "BALANCED")
    engine.start_run(run)
    assert run.status is RunStatus.CLASSIFYING


def test_fail_run_from_every_active_state():
    for status in RunStatus:
        if not status.is_active:
            continue
        engine = RunEngine()
        run = engine.create_run("t", "FAST", run_id=f"r-{status.value}")
        run.status = status  # position the run where we want it
        engine.fail_run(run, error="boom")
        assert run.status is RunStatus.FAILED
        assert run.error == "boom"
        assert run.completed_at is None
        assert engine.events[-1].event_type == RUN_FAILED


def test_complete_run_only_from_verifying():
    engine = RunEngine()
    run = engine.create_run("report", "BALANCED")
    with pytest.raises(InvalidStateTransition):
        engine.complete_run(run)
    assert run.status is not RunStatus.COMPLETED

    run.status = RunStatus.VERIFYING
    engine.complete_run(run, result={"rows": 10})
    assert run.status is RunStatus.COMPLETED
    assert run.result == {"rows": 10}
    assert run.completed_at is not None


def test_terminal_runs_reject_any_further_action():
    engine = RunEngine()
    run = engine.create_run("t", "FAST")
    engine.fail_run(run)
    with pytest.raises(InvalidStateTransition):
        engine.start_run(run)
    with pytest.raises(InvalidStateTransition):
        engine.complete_run(run)


def test_full_lifecycle_events_and_timestamps():
    clock = _Clock()
    engine = RunEngine(clock=clock)
    run = engine.create_run("report", "BALANCED", run_id="run-1")
    for target in (
        RunStatus.CLASSIFYING,
        RunStatus.PLANNING,
        RunStatus.RUNNING,
        RunStatus.TOOL_EXECUTION,
        RunStatus.VERIFYING,
    ):
        engine.transition(run, target)
    clock.advance(minutes=1)
    engine.complete_run(run, result={"ok": True})

    types = [e.event_type for e in engine.events]
    assert types[0] == RUN_CREATED
    assert types.count(STATE_CHANGED) == 6  # 5 transitions + COMPLETED
    assert types[-1] == RUN_COMPLETED
    assert all(e.run_id == "run-1" for e in engine.events)
    assert run.started_at == clock.now - timedelta(minutes=1)
    assert run.completed_at == clock.now


def test_started_at_stamped_on_first_running_entry():
    clock = _Clock()
    engine = RunEngine(clock=clock)
    run = engine.create_run("t", "FAST", run_id="r")
    run.status = RunStatus.APPROVED
    engine.transition(run, RunStatus.RUNNING)
    assert run.started_at == clock.now


def test_agent_run_serialization():
    engine = RunEngine()
    run = engine.create_run("report", "BALANCED", run_id="run-s")
    run.status = RunStatus.VERIFYING
    data = run.to_dict()
    assert data["id"] == "run-s"
    assert data["status"] == "verifying"
    assert data["task_type"] == "report"
    assert data["model_profile"] == "BALANCED"
    assert data["created_at"] is not None
    assert data["started_at"] is None


def test_cancel_run_is_terminal():
    engine = RunEngine()
    run = engine.create_run("t", "FAST", run_id="r")
    for target in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.RUNNING):
        engine.transition(run, target)
    engine.cancel_run(run)
    assert run.status is RunStatus.CANCELLED
    with pytest.raises(InvalidStateTransition):
        engine.start_run(run)
