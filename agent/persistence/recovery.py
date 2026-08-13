"""Recovery classification (Sprint 1.0.3) — READ-ONLY, no auto actions.

Maps persisted run state + event journal to a disposition. Sprint 1.0.3
only CLASSIFIES: nothing is resumed, re-run or retried automatically.
Automatic safe-resume is a later sprint.
"""

from enum import Enum
from typing import Iterable, Optional

from agent.execution.events import TOOL_COMPLETED, TOOL_STARTED
from agent.runtime.states import RunStatus

# Crash-critical tool verbs: if a TOOL_STARTED exists without a matching
# TOOL_COMPLETED, these must NEVER auto-repeat.
NON_IDEMPOTENT_TOOL_HINTS = ("send", "delete", "create", "payment", "restart", "deploy")


class RecoveryDisposition(Enum):
    SAFE_TO_RESUME = "safe_to_resume"
    WAIT_FOR_APPROVAL = "wait_for_approval"
    REQUIRES_VERIFICATION = "requires_verification"
    MANUAL_REVIEW = "manual_review"
    TERMINAL = "terminal"


def classify(
    run_status: RunStatus,
    events: Optional[Iterable[str]] = None,
) -> RecoveryDisposition:
    """Disposition for a persisted run (events = event_type sequence, in
    journal order). Pure function — no I/O, no side effects."""
    if run_status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        return RecoveryDisposition.TERMINAL

    if run_status is RunStatus.WAITING_APPROVAL:
        return RecoveryDisposition.WAIT_FOR_APPROVAL
    if run_status in (RunStatus.CLASSIFYING, RunStatus.PLANNING, RunStatus.APPROVED):
        return RecoveryDisposition.SAFE_TO_RESUME
    if run_status is RunStatus.VERIFYING:
        return RecoveryDisposition.REQUIRES_VERIFICATION
    if run_status is RunStatus.TOOL_EXECUTION:
        return _tool_disposition(events)
    if run_status is RunStatus.RUNNING:
        return _running_disposition(events)
    # CREATED — nothing started yet.
    return RecoveryDisposition.SAFE_TO_RESUME


def _tool_disposition(events: Optional[Iterable[str]]) -> RecoveryDisposition:
    """A tool was in flight when the process died.

    TOOL_COMPLETED after the last TOOL_STARTED → the tool finished but the
    result was not persisted: REQUIRES_VERIFICATION. Otherwise (TOOL_STARTED
    without completion) → MANUAL_REVIEW — never auto-repeat.
    """
    if _tool_proved_completed(events):
        return RecoveryDisposition.REQUIRES_VERIFICATION
    return RecoveryDisposition.MANUAL_REVIEW


def _running_disposition(events: Optional[Iterable[str]]) -> RecoveryDisposition:
    """RUNNING is ambiguous: depends on the last journal entry.

    - last event TOOL_STARTED without TOOL_COMPLETED → MANUAL_REVIEW
    - last event TOOL_COMPLETED / STEP_STARTED (between steps) → SAFE_TO_RESUME
    - otherwise → REQUIRES_VERIFICATION
    """
    seq = list(events or [])
    if not seq:
        return RecoveryDisposition.REQUIRES_VERIFICATION
    last = seq[-1]
    if last == TOOL_STARTED and not _tool_proved_completed(seq):
        return RecoveryDisposition.MANUAL_REVIEW
    if last in (TOOL_COMPLETED, "STEP_STARTED", "PLAN_CREATED"):
        return RecoveryDisposition.SAFE_TO_RESUME
    return RecoveryDisposition.REQUIRES_VERIFICATION


def _tool_proved_completed(events: Optional[Iterable[str]]) -> bool:
    seq = list(events or [])
    if not seq:
        return False
    last_start = max(
        (i for i, t in enumerate(seq) if t == TOOL_STARTED), default=-1
    )
    return any(t == TOOL_COMPLETED and i > last_start for i, t in enumerate(seq))
