"""Run lifecycle states (Sprint 1.0.1)."""

from enum import Enum


class RunStatus(Enum):
    CREATED = "created"
    CLASSIFYING = "classifying"
    PLANNING = "planning"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    TOOL_EXECUTION = "tool_execution"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        """True for any non-terminal state (may still move to FAILED/CANCELLED)."""
        return self not in TERMINAL_STATES

    @property
    def is_terminal(self) -> bool:
        """True once the run can never change state again."""
        return self in TERMINAL_STATES


TERMINAL_STATES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)
