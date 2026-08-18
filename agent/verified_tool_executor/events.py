"""Execution event emission (Sprint 1.3.2 §18-§20).

The audit trail stays ONE uniform stream: event OBJECTS are the
existing :class:`agent.runtime.events.RuntimeEvent`, and the type
constants (TOOL_STARTED / TOOL_COMPLETED / TOOL_FAILED) are the
existing Sprint 1.0.2 execution constants — this layer only re-exports
them so the executor can emit without importing the whole execution
engine.

Contract:

- TOOL_STARTED  — emitted BEFORE actual invocation, carries
                  execution_id + tool + input_hash, NO raw args (§18).
- TOOL_COMPLETED — emitted ONLY after a successfully VALIDATED result,
                  carries output_hash (§19).
- TOOL_FAILED   — normalized: error_class + error_code + retryable,
                  NO traceback in public telemetry (§20).
"""

from datetime import datetime, timezone
from typing import Any, Callable, List

from agent.runtime.events import RuntimeEvent

from agent.execution.events import (
    TOOL_COMPLETED,
    TOOL_FAILED,
    TOOL_STARTED,
)

#: Full set of executor event types (subset of the execution stream).
EXECUTOR_EVENT_TYPES = frozenset({TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED})


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

__all__ = [
    "TOOL_STARTED",
    "TOOL_COMPLETED",
    "TOOL_FAILED",
    "EXECUTOR_EVENT_TYPES",
    "RuntimeEvent",
    "emit",
    "utcnow",
    "Clock",
]
