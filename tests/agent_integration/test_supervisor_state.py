"""Supervisor state machine + retry rules + failed-agent exclusion (Phase 6 §12, §23)."""

import pytest

from agent.agent_integration.supervisor_state import (
    AgentRunState,
    AgentRunStateMachine,
    InvalidRunTransition,
    RetryVerdict,
    bounded_retry_decision,
    exclude_failed,
)


def test_legal_ready_to_running():
    sm = AgentRunStateMachine(AgentRunState.READY)
    sm2 = sm.transition(AgentRunState.RUNNING)
    assert sm2.state is AgentRunState.RUNNING


def test_illegal_ready_to_completed():
    with pytest.raises(InvalidRunTransition):
        AgentRunStateMachine(AgentRunState.READY).transition(AgentRunState.COMPLETED)


def test_unknown_must_go_to_human_review():
    sm = AgentRunStateMachine(AgentRunState.UNKNOWN)
    assert sm.can_transition_to(AgentRunState.HUMAN_REVIEW) is True
    # UNKNOWN cannot auto-return to RUNNING/COMPLETED (fail-closed).
    assert sm.can_transition_to(AgentRunState.RUNNING) is False
    assert sm.can_transition_to(AgentRunState.COMPLETED) is False


def test_terminal_states_are_immutable():
    for terminal in (AgentRunState.COMPLETED, AgentRunState.HUMAN_REVIEW):
        sm = AgentRunStateMachine(terminal)
        assert sm.is_terminal is True
        for target in AgentRunState:
            assert sm.can_transition_to(target) is False


def test_running_to_allowed_dispositions():
    sm = AgentRunStateMachine(AgentRunState.RUNNING)
    for target in (AgentRunState.WAITING, AgentRunState.COMPLETED, AgentRunState.FAILED,
                   AgentRunState.UNKNOWN, AgentRunState.HUMAN_REVIEW):
        assert sm.can_transition_to(target) is True


def test_bounded_retry_read_only_idempotent_within_budget():
    verdict = bounded_retry_decision(
        is_read_only=True, is_idempotent=True, prior_state=AgentRunState.FAILED,
        attempts_used=0, max_retries=1,
    )
    assert verdict.retry_allowed is True


def test_bounded_retry_unknown_never_retried():
    for prior in (AgentRunState.UNKNOWN, AgentRunState.HUMAN_REVIEW):
        verdict = bounded_retry_decision(
            is_read_only=True, is_idempotent=True, prior_state=prior,
            attempts_used=0, max_retries=3,
        )
        assert verdict.retry_allowed is False


def test_bounded_retry_non_read_only_never_retried():
    verdict = bounded_retry_decision(
        is_read_only=False, is_idempotent=True, prior_state=AgentRunState.FAILED,
        attempts_used=0, max_retries=3,
    )
    assert verdict.retry_allowed is False


def test_bounded_retry_non_idempotent_never_retried():
    verdict = bounded_retry_decision(
        is_read_only=True, is_idempotent=False, prior_state=AgentRunState.FAILED,
        attempts_used=0, max_retries=3,
    )
    assert verdict.retry_allowed is False


def test_bounded_retry_budget_exhausted():
    verdict = bounded_retry_decision(
        is_read_only=True, is_idempotent=True, prior_state=AgentRunState.FAILED,
        attempts_used=5, max_retries=5,
    )
    assert verdict.retry_allowed is False


def test_bounded_retry_validates_attempts():
    with pytest.raises(ValueError):
        bounded_retry_decision(is_read_only=True, is_idempotent=True,
                               prior_state=AgentRunState.FAILED, attempts_used=-1,
                               max_retries=1)


def test_exclude_failed_removes_failed_agent():
    pruned = exclude_failed({"monitoring", "research"}, "monitoring")
    assert "monitoring" not in pruned
    assert "research" in pruned


def test_exclude_failed_never_returns_failed_agent():
    # Even when the failed agent is the only alternative, routing must not
    # reselect it (fail-closed: the caller surfaces NO_ROUTE instead).
    with pytest.raises(InvalidRunTransition):
        exclude_failed({"monitoring"}, "monitoring")
    # A set without the failed agent is passed through unchanged.
    assert exclude_failed({"research"}, "monitoring") == frozenset({"research"})


def test_same_agent_not_reselected_after_failure():
    # ORCH-003: alternative route must exclude the failed agent.
    assert "A" not in exclude_failed({"A", "B"}, "A")