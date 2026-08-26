"""Worker append-only audit chain (Phase 8.3 §20).

The worker records an ordered, append-only chain of DATA events for each
envelope it receives.  An audit event is never authority: it can never be
replayed as an execution instruction, an override, or a grant, and writing an
audit event performs no production action.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class WorkerAuditKind(Enum):
    ENVELOPE_RECEIVED = "envelope_received"
    ENVELOPE_VALIDATED = "envelope_validated"
    CLAIM_ACQUIRED = "claim_acquired"
    TASK_CREATED = "task_created"
    ROUTE_SELECTED = "route_selected"
    MEMORY_CONTEXT_BUILT = "memory_context_built"
    BOUNDARY_DECIDED = "boundary_decided"
    OBSERVATION_CREATED = "observation_created"
    SUPERVISOR_DISPOSITION = "supervisor_disposition"
    COMPARISON_RECORDED = "comparison_recorded"
    WORKER_COMPLETED = "worker_completed"


WORKER_AUDIT_CHAIN_ORDER = tuple(k.value for k in WorkerAuditKind)


@dataclass(frozen=True, slots=True)
class WorkerAuditEvent:
    sequence: int
    event_id: str
    tenant_id: str
    kind: WorkerAuditKind
    detail: str
    timestamp: float


class WorkerAuditStore:
    """Append-only, thread-safe worker audit; bounded by ``max_events``."""

    __slots__ = ("_events", "_lock", "_clock", "_max")

    def __init__(self, *, clock: Callable[[], float] | None = None,
                 max_events: int = 100_000) -> None:
        if not isinstance(max_events, int) or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        self._events: list[WorkerAuditEvent] = []
        self._lock = threading.Lock()
        self._clock = clock if clock is not None else time.time
        self._max = max_events

    def append(self, *, event_id: str, tenant_id: str, kind: WorkerAuditKind,
               detail: str = "") -> WorkerAuditEvent:
        if type(kind) is not WorkerAuditKind:
            raise ValueError("kind must be an exact WorkerAuditKind value")
        event = WorkerAuditEvent(
            sequence=len(self._events),
            event_id=event_id,
            tenant_id=tenant_id,
            kind=kind,
            detail=detail,
            timestamp=float(self._clock()),
        )
        with self._lock:
            if len(self._events) >= self._max:
                raise OverflowError("worker audit store full (append-only, no drop)")
            self._events.append(event)
        return event

    def for_event(self, event_id: str) -> tuple[WorkerAuditEvent, ...]:
        with self._lock:
            return tuple(e for e in self._events if e.event_id == event_id)

    def chain_kinds(self, event_id: str) -> tuple[str, ...]:
        return tuple(e.kind.value for e in self.for_event(event_id))

    def count(self) -> int:
        with self._lock:
            return len(self._events)

    def snapshot(self) -> tuple[WorkerAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)


__all__ = [
    "WORKER_AUDIT_CHAIN_ORDER",
    "WorkerAuditEvent",
    "WorkerAuditKind",
    "WorkerAuditStore",
]