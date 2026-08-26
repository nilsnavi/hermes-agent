"""Agent coordination state machine tests."""

import pytest

from agent.agent_orchestration.coordination import (
    CoordinationState,
    CoordinationStatus,
    InvalidCoordinationTransition,
)


def test_new_state_starts_analyzing():
    state = CoordinationState()
    assert state.status is CoordinationStatus.ANALYZING
    assert state.version == 0


def test_legal_progression():
    state = CoordinationState()
    planning = state.transition(CoordinationStatus.PLANNING)
    routing = planning.transition(CoordinationStatus.ROUTING)
    supervising = routing.transition(CoordinationStatus.SUPERVISING)
    validating = supervising.transition(CoordinationStatus.VALIDATING)
    completed = validating.transition(CoordinationStatus.COMPLETED)
    assert completed.is_terminal


def test_illegal_skip_rejected():
    state = CoordinationState()
    with pytest.raises(InvalidCoordinationTransition):
        state.transition(CoordinationStatus.SUPERVISING)


def test_terminal_is_immutable():
    completed = (
        CoordinationState()
        .transition(CoordinationStatus.PLANNING)
        .transition(CoordinationStatus.ROUTING)
        .transition(CoordinationStatus.SUPERVISING)
        .transition(CoordinationStatus.VALIDATING)
        .transition(CoordinationStatus.COMPLETED)
    )
    assert completed.is_terminal
    with pytest.raises(InvalidCoordinationTransition):
        completed.transition(CoordinationStatus.FAILED)


def test_cancel_from_supervising():
    cancelled = (
        CoordinationState()
        .transition(CoordinationStatus.PLANNING)
        .transition(CoordinationStatus.ROUTING)
        .transition(CoordinationStatus.SUPERVISING)
        .transition(CoordinationStatus.CANCELLED)
    )
    assert cancelled.is_terminal


def test_coordination_holds_no_execution_authority():
    state = CoordinationState()
    assert not hasattr(state, "execute")
    assert not hasattr(state, "dispatch")
    assert not hasattr(state, "authorize")


def test_transition_rejects_non_status():
    state = CoordinationState()
    with pytest.raises(InvalidCoordinationTransition):
        state.transition("planning")  # type: ignore[arg-type]