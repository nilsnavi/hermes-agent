"""Supervisor run-state for the read-only vertical (Phase 6 §12, §23).

``AgentRunState`` is a closed state vocabulary with fail-closed transitions.
Rules: UNKNOWN -> HUMAN_REVIEW; a side-effect-unknown attempt -> HUMAN_REVIEW;
TIMEOUT -> a bounded retry is allowed ONLY for a proven read-only, idempotent
operation; a mutation-like unknown is NEVER retried. Phase 6 operations are
read-only by construction. This module also provides the failed-agent exclusion
(ORCH-003): when rerouting after a failure, the failed agent id is placed in
the exclude set so the same agent is not immediately re-selected.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import AbstractSet


class InvalidRunTransition(ValueError):
    """Raised on an illegal run-state transition."""


class AgentRunState(Enum):
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    HUMAN_REVIEW = "human_review"


_FORWARD: dict[AgentRunState, frozenset[AgentRunState]] = {
    AgentRunState.READY: frozenset({AgentRunState.RUNNING}),
    AgentRunState.RUNNING: frozenset(
        {
            AgentRunState.WAITING,
            AgentRunState.COMPLETED,
            AgentRunState.FAILED,
            AgentRunState.UNKNOWN,
            AgentRunState.HUMAN_REVIEW,
        }
    ),
    AgentRunState.WAITING: frozenset({AgentRunState.RUNNING}),
    AgentRunState.COMPLETED: frozenset(),
    AgentRunState.FAILED: frozenset({AgentRunState.HUMAN_REVIEW, AgentRunState.RUNNING}),
    AgentRunState.UNKNOWN: frozenset({AgentRunState.HUMAN_REVIEW}),
    AgentRunState.HUMAN_REVIEW: frozenset(),
}

_TERMINAL = frozenset({AgentRunState.COMPLETED, AgentRunState.HUMAN_REVIEW})


class AgentRunStateMachine:
    """Immutable state machine over AgentRunState (fail-closed transitions)."""

    __slots__ = ("_state",)

    def __init__(self, state: AgentRunState = AgentRunState.READY) -> None:
        if type(state) is not AgentRunState:
            raise InvalidRunTransition("state must be an exact AgentRunState value")
        self._state = state

    @property
    def state(self) -> AgentRunState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in _TERMINAL

    def can_transition_to(self, to_state: AgentRunState) -> bool:
        if type(to_state) is not AgentRunState:
            return False
        return to_state in _FORWARD.get(self._state, frozenset())

    def transition(self, to_state: AgentRunState) -> "AgentRunStateMachine":
        if type(to_state) is not AgentRunState:
            raise InvalidRunTransition("to_state must be an exact AgentRunState value")
        if not self.can_transition_to(to_state):
            raise InvalidRunTransition(
                f"cannot transition from {self._state.value} to {to_state.value}"
            )
        return AgentRunStateMachine(to_state)


@dataclass(frozen=True, slots=True)
class RetryVerdict:
    """Whether a bounded retry of the SAME agent is permitted."""

    retry_allowed: bool
    reason: str


def bounded_retry_decision(
    *,
    is_read_only: bool,
    is_idempotent: bool,
    prior_state: AgentRunState,
    attempts_used: int,
    max_retries: int = 1,
) -> RetryVerdict:
    """Bounded retry only for a proven read-only, idempotent operation.

    UNKNOWN / HUMAN_REVIEW / a mutation-like (non-read-only) attempt are NEVER
    auto-retried (fail-closed). Phase 6 read-only operations may retry within
    budget.
    """
    if prior_state in (AgentRunState.UNKNOWN, AgentRunState.HUMAN_REVIEW):
        return RetryVerdict(False, "unknown/human-review outcome is not auto-retried")
    if not is_read_only:
        return RetryVerdict(False, "non-read-only operation is never auto-retried")
    if not is_idempotent:
        return RetryVerdict(False, "non-idempotent read operation is not auto-retried")
    if isinstance(attempts_used, bool) or not isinstance(attempts_used, int) or attempts_used < 0:
        raise ValueError("attempts_used must be a non-negative integer")
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ValueError("max_retries must be a non-negative integer")
    if attempts_used >= max_retries:
        return RetryVerdict(False, "retry budget exhausted")
    return RetryVerdict(True, "proven read-only and idempotent within retry budget")


def exclude_failed(
    alternative_ids: AbstractSet[str], failed_agent_id: str
) -> frozenset[str]:
    """ORCH-003: remove the failed agent from the alternative candidate set.

    Returns the filtered set (which may be empty -- the caller then surfaces
    NO_ROUTE instead of re-selecting the failed agent). The failed agent is
    NEVER re-selected on an alternative routing.
    """
    if not isinstance(failed_agent_id, str) or not failed_agent_id.strip():
        raise ValueError("failed_agent_id must be a non-empty string")
    result = frozenset(alt for alt in alternative_ids if alt != failed_agent_id)
    if failed_agent_id in alternative_ids:
        # Fail-closed: assert a routing even happened when alternatives were
        # given explicitly (so an empty prune is never silently interpreted as
        # "keep the failed agent").
        if len(result) == 0:
            raise InvalidRunTransition(
                "cannot create an alternative route: only the failed agent was eligible"
            )
    return result


__all__ = [
    "AgentRunState",
    "AgentRunStateMachine",
    "InvalidRunTransition",
    "RetryVerdict",
    "bounded_retry_decision",
    "exclude_failed",
]