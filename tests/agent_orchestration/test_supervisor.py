"""Supervisor contract tests: fail-closed outcome disposition."""

import pytest

from agent.agent_orchestration.supervisor import (
    AttemptContext,
    EscalationEvent,
    InvalidSupervisorDecision,
    OutcomeDisposition,
    OutcomeKind,
    SupervisorPolicy,
)


def _ctx(*, attempt=1, max_retries=1, alternatives=0, side_effect=False,
         outcome=OutcomeKind.FAILED) -> AttemptContext:
    return AttemptContext(
        attempt=attempt,
        max_retries=max_retries,
        alternative_count=alternatives,
        has_side_effect_evidence=side_effect,
        outcome=outcome,
    )


def test_success_is_none():
    assert SupervisorPolicy.decide(
        _ctx(outcome=OutcomeKind.SUCCESS)
    ) is OutcomeDisposition.NONE


def test_failed_within_budget_retries_safe():
    assert SupervisorPolicy.decide(_ctx(attempt=1, max_retries=2)) is OutcomeDisposition.RETRY_SAFE


def test_failed_exhausted_with_no_alternative_escalates():
    assert SupervisorPolicy.decide(
        _ctx(attempt=3, max_retries=2, alternatives=0)
    ) is OutcomeDisposition.ESCALATE


def test_failed_exhausted_with_alternative_routes_alternative():
    assert SupervisorPolicy.decide(
        _ctx(attempt=3, max_retries=2, alternatives=1),
        alternative_ids={"agent-b"},
    ) is OutcomeDisposition.ALTERNATIVE


def test_unknown_outcome_always_human_review():
    assert SupervisorPolicy.decide(
        _ctx(outcome=OutcomeKind.UNKNOWN)
    ) is OutcomeDisposition.HUMAN_REVIEW


def test_timeout_always_human_review():
    assert SupervisorPolicy.decide(
        _ctx(outcome=OutcomeKind.TIMEOUT)
    ) is OutcomeDisposition.HUMAN_REVIEW


def test_side_effect_evidence_never_auto_retried():
    assert SupervisorPolicy.decide(
        _ctx(side_effect=True, outcome=OutcomeKind.FAILED)
    ) is OutcomeDisposition.HUMAN_REVIEW


def test_side_effect_evidence_on_unknown_also_human_review():
    assert SupervisorPolicy.decide(
        _ctx(side_effect=True, outcome=OutcomeKind.UNKNOWN)
    ) is OutcomeDisposition.HUMAN_REVIEW


def test_rejected_escalates():
    assert SupervisorPolicy.decide(
        _ctx(outcome=OutcomeKind.REJECTED)
    ) is OutcomeDisposition.ESCALATE


def test_no_blind_recovery_from_unknown():
    # An unknown outcome never auto-retries regardless of budget.
    for attempt in (1, 5):
        assert SupervisorPolicy.decide(
            _ctx(attempt=attempt, max_retries=10, outcome=OutcomeKind.UNKNOWN)
        ) is OutcomeDisposition.HUMAN_REVIEW


def test_decide_rejects_bad_ctx_type():
    with pytest.raises(InvalidSupervisorDecision):
        SupervisorPolicy.decide(object())  # type: ignore[arg-type]


def test_attempt_context_validates():
    with pytest.raises(InvalidSupervisorDecision):
        AttemptContext(0, 1, 0, False, OutcomeKind.FAILED)
    with pytest.raises(InvalidSupervisorDecision):
        AttemptContext(1, -1, 0, False, OutcomeKind.FAILED)
    with pytest.raises(InvalidSupervisorDecision):
        AttemptContext(1, 1, -1, False, OutcomeKind.FAILED)
    with pytest.raises(InvalidSupervisorDecision):
        AttemptContext(1, 1, 0, "no", OutcomeKind.FAILED)  # type: ignore[arg-type]
    with pytest.raises(InvalidSupervisorDecision):
        AttemptContext(1, 1, 0, False, "failed")  # type: ignore[arg-type]


def test_alternative_ids_validated():
    with pytest.raises(InvalidSupervisorDecision):
        SupervisorPolicy.decide(
            _ctx(attempt=3, max_retries=2, alternatives=1),
            alternative_ids={" "},
        )


def test_escalation_event_validates():
    with pytest.raises(InvalidSupervisorDecision):
        EscalationEvent("", "s", "r", "why", OutcomeDisposition.ESCALATE)
    with pytest.raises(InvalidSupervisorDecision):
        EscalationEvent("t", "s", "r", "why", "escalate")  # type: ignore[arg-type]


def test_supervisor_policy_has_no_execution_surface():
    # The supervisor returns dispositions; it never executes or authorizes.
    assert not hasattr(SupervisorPolicy, "execute")
    assert not hasattr(SupervisorPolicy, "run")
    assert not hasattr(SupervisorPolicy, "authorize")
    assert not hasattr(SupervisorPolicy, "grant")