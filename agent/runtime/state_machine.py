"""Deterministic, fail-closed run state machine (Sprint 1.0.1).

No automatic transitions: every status change is an explicit caller action
validated against the static edge table below. Unknown statuses resolve to
no outgoing edges (fail closed); terminal states have no outgoing edges.
"""

from typing import Dict, FrozenSet

from .exceptions import InvalidStateTransition
from .states import RunStatus

# Forward-only edge table. Every active state may also move to FAILED
# (error flow) or CANCELLED (operator abort); both are terminal.
_ALLOWED: Dict[RunStatus, FrozenSet[RunStatus]] = {
    RunStatus.CREATED: frozenset(
        {RunStatus.CLASSIFYING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.CLASSIFYING: frozenset(
        {RunStatus.PLANNING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    # PLANNING -> RUNNING: direct start when approval is not required.
    RunStatus.PLANNING: frozenset(
        {RunStatus.WAITING_APPROVAL, RunStatus.RUNNING,
         RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.WAITING_APPROVAL: frozenset(
        {RunStatus.APPROVED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.APPROVED: frozenset(
        {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.RUNNING: frozenset(
        {RunStatus.TOOL_EXECUTION, RunStatus.VERIFYING,
         RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.TOOL_EXECUTION: frozenset(
        {RunStatus.VERIFYING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.VERIFYING: frozenset(
        {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    """True iff ``target`` is a legal successor of ``current``."""
    return target in _ALLOWED.get(current, frozenset())


def transition(run, target: RunStatus) -> RunStatus:
    """Move *run* to *target*, raising InvalidStateTransition when forbidden.

    Pure status change: timestamps and events are owned by the RunEngine.
    On failure the run's status is left untouched (fail closed).
    """
    if not can_transition(run.status, target):
        raise InvalidStateTransition(run.status, target)
    run.status = target
    return target
