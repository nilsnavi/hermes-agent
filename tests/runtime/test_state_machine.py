"""State machine tests (Sprint 1.0.1): deterministic, fail-closed transitions."""

from datetime import datetime, timezone

import pytest

from agent.runtime.exceptions import InvalidStateTransition
from agent.runtime.models import AgentRun
from agent.runtime.state_machine import can_transition, transition
from agent.runtime.states import RunStatus


def _run(status=RunStatus.CREATED):
    return AgentRun(
        id="r1",
        task_type="test",
        status=status,
        model_profile="BALANCED",
        created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    "current,target",
    [
        # Sprint spec — happy path
        (RunStatus.CREATED, RunStatus.CLASSIFYING),
        (RunStatus.CLASSIFYING, RunStatus.PLANNING),
        (RunStatus.PLANNING, RunStatus.RUNNING),  # no-approval shortcut
        (RunStatus.RUNNING, RunStatus.VERIFYING),
        (RunStatus.VERIFYING, RunStatus.COMPLETED),
        # Full diagram incl. approval gate
        (RunStatus.PLANNING, RunStatus.WAITING_APPROVAL),
        (RunStatus.WAITING_APPROVAL, RunStatus.APPROVED),
        (RunStatus.APPROVED, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.TOOL_EXECUTION),
        (RunStatus.TOOL_EXECUTION, RunStatus.VERIFYING),
        # Error / abort flows
        (RunStatus.CREATED, RunStatus.FAILED),
        (RunStatus.CLASSIFYING, RunStatus.CANCELLED),
        (RunStatus.TOOL_EXECUTION, RunStatus.FAILED),
        (RunStatus.VERIFYING, RunStatus.CANCELLED),
    ],
)
def test_valid_transitions(current, target):
    assert can_transition(current, target) is True


@pytest.mark.parametrize(
    "current,target",
    [
        # Sprint spec — forbidden
        (RunStatus.CREATED, RunStatus.COMPLETED),
        (RunStatus.COMPLETED, RunStatus.RUNNING),
        (RunStatus.FAILED, RunStatus.RUNNING),
        # Terminals are absorbing
        (RunStatus.COMPLETED, RunStatus.FAILED),
        (RunStatus.FAILED, RunStatus.CANCELLED),
        (RunStatus.CANCELLED, RunStatus.RUNNING),
        (RunStatus.CANCELLED, RunStatus.CREATED),
        # No self-loops, no backwards edges
        (RunStatus.CREATED, RunStatus.CREATED),
        (RunStatus.RUNNING, RunStatus.CREATED),
        (RunStatus.RUNNING, RunStatus.PLANNING),
    ],
)
def test_invalid_transitions(current, target):
    assert can_transition(current, target) is False


def test_error_flow_from_any_active_state():
    for status in RunStatus:
        if status.is_active:
            assert can_transition(status, RunStatus.FAILED) is True
        else:
            assert can_transition(status, RunStatus.FAILED) is False


def test_transition_mutates_status():
    run = _run()
    transition(run, RunStatus.CLASSIFYING)
    assert run.status is RunStatus.CLASSIFYING


def test_transition_raises_and_leaves_run_unchanged():
    run = _run()
    with pytest.raises(InvalidStateTransition) as excinfo:
        transition(run, RunStatus.COMPLETED)
    assert excinfo.value.current is RunStatus.CREATED
    assert excinfo.value.target is RunStatus.COMPLETED
    assert "created -> completed" in str(excinfo.value)
    assert run.status is RunStatus.CREATED  # fail closed


def test_unknown_status_fails_closed():
    # A corrupted status must resolve to zero outgoing edges, not crash.
    run = _run(status="bogus")  # type: ignore[arg-type]
    assert can_transition(run.status, RunStatus.RUNNING) is False
    with pytest.raises(InvalidStateTransition):
        transition(run, RunStatus.RUNNING)
