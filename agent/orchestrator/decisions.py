"""Loop decisions + structured stop reasons (Sprint 1.0.5).

The stop reason is ALWAYS a structured enum value — free text is only ever
an optional *error* detail, never the source of truth.
"""

from enum import Enum


class LoopDecision(Enum):
    CONTINUE = "continue"
    WAIT_APPROVAL = "wait_approval"
    VERIFY = "verify"
    COMPLETE = "complete"
    FAIL = "fail"
    CANCEL = "cancel"
    MANUAL_REVIEW = "manual_review"
    BUDGET_EXCEEDED = "budget_exceeded"


class StopReason(Enum):
    COMPLETED = "completed"
    APPROVAL_REQUIRED = "approval_required"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    MAX_STEPS = "max_steps"
    MAX_TOOL_CALLS = "max_tool_calls"
    MAX_REPLANS = "max_replans"
    MAX_FAILURES = "max_failures"
    RUNTIME_TIMEOUT = "runtime_timeout"
    CANCELLED = "cancelled"
    EXECUTION_FAILED = "execution_failed"
    NO_PLAN = "no_plan"
    INVALID_PLAN = "invalid_plan"
    VERIFICATION_FAILED = "verification_failed"
