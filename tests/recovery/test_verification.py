"""Verification recovery tests (Sprint 1.0.4)."""

from datetime import datetime, timezone

import pytest

from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from agent.persistence import SQLiteExecutionStore
from agent.recovery import VerificationRecovery
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus

T0 = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = SQLiteExecutionStore(str(tmp_path / "state.db"))
    yield s
    s.close()


def _run(store, status=RunStatus.RUNNING):
    run = AgentRun(id="run-1", task_type="t", status=status,
                   model_profile="BALANCED", created_at=T0)
    store.save_run(run)
    return run


def _event(event_type, step=None):
    payload = {"step": step} if step else {}
    return RuntimeEvent(event_type=event_type, run_id="run-1",
                        timestamp=T0, payload=payload)


def _save_plan(store, steps):
    plan = ExecutionPlan(id="plan-1", run_id="run-1", goal="g",
                         status=PlanStatus.RUNNING, created_at=T0)
    store.save_plan(plan)
    for step in steps:
        store.save_step("plan-1", step)


def test_verify_ok_when_all_tools_proved_completed(store):
    _run(store)
    _save_plan(store, [
        ExecutionStep(id="s1", name="n", description="", tool="t",
                      status=StepStatus.COMPLETED, result={"output": {"ok": 1}}),
    ])
    store.append_event(_event("STEP_STARTED", "s1"))
    store.append_event(_event("TOOL_STARTED", "s1"))
    store.append_event(_event("TOOL_COMPLETED", "s1"))

    verdict = VerificationRecovery(store).verify(store.get_run("run-1"))

    assert verdict.ok is True
    assert verdict.missing_steps == []
    assert verdict.reasons == []


def test_verify_missing_completion_detected(store):
    _run(store)
    _save_plan(store, [
        ExecutionStep(id="s1", name="n", description="", tool="t",
                      status=StepStatus.RUNNING),
    ])
    store.append_event(_event("STEP_STARTED", "s1"))
    store.append_event(_event("TOOL_STARTED", "s1"))  # crash here

    verdict = VerificationRecovery(store).verify(store.get_run("run-1"))

    assert verdict.ok is False
    assert verdict.missing_steps == ["s1"]
    assert "TOOL_STARTED without TOOL_COMPLETED" in verdict.reasons[0]


def test_verify_multiple_steps_pairs_independently(store):
    """s1 proved complete, s2 unconfirmed — only s2 is missing."""
    _run(store)
    _save_plan(store, [
        ExecutionStep(id="s1", name="n", description="", tool="t",
                      status=StepStatus.COMPLETED, result={"output": {}}),
        ExecutionStep(id="s2", name="n", description="", tool="t",
                      status=StepStatus.RUNNING),
    ])
    for step in ("s1", "s2"):
        store.append_event(_event("STEP_STARTED", step))
    store.append_event(_event("TOOL_STARTED", "s1"))
    store.append_event(_event("TOOL_COMPLETED", "s1"))
    store.append_event(_event("TOOL_STARTED", "s2"))  # crash mid s2

    verdict = VerificationRecovery(store).verify(store.get_run("run-1"))

    assert verdict.ok is False
    assert verdict.missing_steps == ["s2"]


def test_verify_flags_completed_without_result(store):
    """Data inconsistency: COMPLETED row with no persisted result."""
    _run(store)
    _save_plan(store, [
        ExecutionStep(id="s1", name="n", description="", tool="t",
                      status=StepStatus.COMPLETED, result=None),
    ])
    store.append_event(_event("STEP_STARTED", "s1"))
    store.append_event(_event("TOOL_STARTED", "s1"))
    store.append_event(_event("TOOL_COMPLETED", "s1"))

    verdict = VerificationRecovery(store).verify(store.get_run("run-1"))

    assert verdict.ok is False
    assert "s1" in verdict.missing_steps


def test_verify_empty_run_is_ok(store):
    """No tools ever started → nothing unconfirmed."""
    _run(store)
    verdict = VerificationRecovery(store).verify(store.get_run("run-1"))
    assert verdict.ok is True
