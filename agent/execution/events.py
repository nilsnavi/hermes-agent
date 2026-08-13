"""Execution event types (Sprint 1.0.2).

Event OBJECTS are the existing :class:`agent.runtime.events.RuntimeEvent` —
this layer only adds the execution-specific type constants and a tiny emit
helper, so the whole audit trail is one uniform stream.
"""

from datetime import datetime, timezone
from typing import Any, Callable, List

from agent.runtime.events import RuntimeEvent

PLAN_CREATED = "PLAN_CREATED"
STEP_STARTED = "STEP_STARTED"
STEP_WAITING_APPROVAL = "STEP_WAITING_APPROVAL"
STEP_APPROVED = "STEP_APPROVED"
STEP_REJECTED = "STEP_REJECTED"
TOOL_STARTED = "TOOL_STARTED"
TOOL_COMPLETED = "TOOL_COMPLETED"
TOOL_FAILED = "TOOL_FAILED"
EXECUTION_COMPLETED = "EXECUTION_COMPLETED"

EXECUTION_EVENT_TYPES = frozenset(
    {
        PLAN_CREATED,
        STEP_STARTED,
        STEP_WAITING_APPROVAL,
        STEP_APPROVED,
        STEP_REJECTED,
        TOOL_STARTED,
        TOOL_COMPLETED,
        TOOL_FAILED,
        EXECUTION_COMPLETED,
    }
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def emit(
    sink: List[RuntimeEvent],
    event_type: str,
    run_id: str,
    timestamp: datetime,
    **payload: Any,
) -> RuntimeEvent:
    """Append one RuntimeEvent to the shared audit trail and return it."""
    event = RuntimeEvent(
        event_type=event_type,
        run_id=run_id,
        timestamp=timestamp,
        payload=payload,
    )
    sink.append(event)
    return event


Clock = Callable[[], datetime]
