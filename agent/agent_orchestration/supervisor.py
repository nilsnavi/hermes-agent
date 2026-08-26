"""Supervisor contracts: fail-closed outcome disposition.

The supervisor decides what to do with a finished/stalled agent run: retry,
route to an alternative agent, escalate, or escalate to human review. It is a
pure fail-closed classifier. It NEVER executes anything and NEVER grants
execution authority: the returned disposition only selects a path; actual
execution still flows through the verified execution kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import AbstractSet


class OutcomeDisposition(Enum):
    NONE = "none"  # SUCCESS: no supervision action needed.
    RETRY_SAFE = "retry_safe"
    ALTERNATIVE = "alternative"
    ESCALATE = "escalate"
    HUMAN_REVIEW = "human_review"


class OutcomeKind(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    REJECTED = "rejected"


# Outcomes that are NEVER auto-retried or auto-rerouted: an outcome we cannot
# prove to be side-effect-free must go to human review.
_NON_RETRYABLE = frozenset({OutcomeKind.UNKNOWN, OutcomeKind.TIMEOUT})


class InvalidSupervisorDecision(ValueError):
    """Raised on malformed supervisor disposition input."""


@dataclass(frozen=True, slots=True)
class AttemptContext:
    attempt: int
    max_retries: int
    alternative_count: int
    has_side_effect_evidence: bool
    outcome: OutcomeKind

    def __post_init__(self) -> None:
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise InvalidSupervisorDecision("attempt must be a positive integer")
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or self.max_retries < 0
        ):
            raise InvalidSupervisorDecision("max_retries must be a non-negative integer")
        if (
            isinstance(self.alternative_count, bool)
            or not isinstance(self.alternative_count, int)
            or self.alternative_count < 0
        ):
            raise InvalidSupervisorDecision(
                "alternative_count must be a non-negative integer"
            )
        if type(self.has_side_effect_evidence) is not bool:
            raise InvalidSupervisorDecision("has_side_effect_evidence must be a bool")
        if type(self.outcome) is not OutcomeKind:
            raise InvalidSupervisorDecision(
                "outcome must be an exact OutcomeKind value"
            )


class SupervisorPolicy:
    """Pure disposition classifier.

    As a rule object it is stateless and cannot be configured into accepting a
    blind recovery. Retry is allowed only for a safe, idempotent outcome
    within budget; UNKNOWN/TIMEOUT never auto-retry; an attempt with side-effect
    evidence is never retried or rerouted (human review).
    """

    @staticmethod
    def decide(
        ctx: AttemptContext,
        *,
        alternative_ids: AbstractSet[str] = frozenset(),
    ) -> OutcomeDisposition:
        if type(ctx) is not AttemptContext:
            raise InvalidSupervisorDecision("ctx must be an exact AttemptContext value")
        for alternative_id in alternative_ids:
            if not isinstance(alternative_id, str) or not alternative_id.strip():
                raise InvalidSupervisorDecision(
                    "alternative_ids must be non-empty strings"
                )

        # An attempt that may have produced a side effect is never retried.
        if ctx.has_side_effect_evidence and ctx.outcome is not OutcomeKind.SUCCESS:
            return OutcomeDisposition.HUMAN_REVIEW

        if ctx.outcome in _NON_RETRYABLE:
            # Cannot prove an unknown/timeout is side-effect-free; do not auto-execute.
            return OutcomeDisposition.HUMAN_REVIEW

        if ctx.outcome is OutcomeKind.REJECTED:
            return OutcomeDisposition.ESCALATE

        if ctx.outcome is OutcomeKind.SUCCESS:
            return OutcomeDisposition.NONE

        if ctx.outcome is OutcomeKind.FAILED:
            if ctx.attempt <= ctx.max_retries:
                return OutcomeDisposition.RETRY_SAFE
            if alternative_ids:
                return OutcomeDisposition.ALTERNATIVE
            return OutcomeDisposition.ESCALATE

        raise InvalidSupervisorDecision(f"unhandled outcome {ctx.outcome!r}")


@dataclass(frozen=True, slots=True)
class EscalationEvent:
    task_id: str
    step_id: str
    run_id: str
    reason: str
    disposition: OutcomeDisposition

    def __post_init__(self) -> None:
        for name in ("task_id", "step_id", "run_id", "reason"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise InvalidSupervisorDecision(f"{name} must be a non-empty string")
        if type(self.disposition) is not OutcomeDisposition:
            raise InvalidSupervisorDecision(
                "disposition must be an exact OutcomeDisposition value"
            )