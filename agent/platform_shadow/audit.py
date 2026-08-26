"""Shadow append-only audit chain (Phase 7 §13).

Each sampled task yields an ordered chain of immutable audit events. An audit
event is DATA ONLY: it can never be replayed as an execution instruction, an
override, or a grant.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from time import time
from typing import Callable


class ShadowAuditKind(Enum):
    SHADOW_RECEIVED = "shadow_received"
    SHADOW_SAMPLED = "shadow_sampled"
    PLAN_CREATED = "plan_created"
    ROUTE_SELECTED = "route_selected"
    AGENT_RUN_STARTED = "agent_run_started"
    MEMORY_CONTEXT_BUILT = "memory_context_built"
    CAPABILITY_REQUESTED = "capability_requested"
    BOUNDARY_DECIDED = "boundary_decided"
    READ_OBSERVATION = "read_observation"
    SUPERVISOR_DISPOSITION = "supervisor_disposition"
    SHADOW_COMPLETED = "shadow_completed"


SHADOW_AUDIT_CHAIN_ORDER = tuple(kind.value for kind in ShadowAuditKind)


@dataclass(frozen=True, slots=True)
class ShadowAuditEvent:
    """One immutable shadow audit record (data only, never an instruction)."""

    sequence: int
    shadow_id: str
    kind: ShadowAuditKind
    node_id: str
    parent_id: str
    detail: str
    timestamp: float


class ShadowAuditStore:
    """Append-only, thread-safe shadow audit; bounded by ``max_events``."""

    __slots__ = ("_events", "_lock", "_clock", "_max")

    def __init__(self, *, clock: Callable[[], float] | None = None, max_events: int = 100_000) -> None:
        if not isinstance(max_events, int) or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        self._events: list[ShadowAuditEvent] = []
        self._lock = threading.Lock()
        self._clock = clock if clock is not None else time
        self._max = max_events

    def append(
        self,
        *,
        shadow_id: str,
        kind: ShadowAuditKind,
        node_id: str,
        parent_id: str = "",
        detail: str = "",
    ) -> ShadowAuditEvent:
        if type(kind) is not ShadowAuditKind:
            raise ValueError("kind must be an exact ShadowAuditKind value")
        event = ShadowAuditEvent(
            sequence=len(self._events),
            shadow_id=shadow_id,
            kind=kind,
            node_id=node_id,
            parent_id=parent_id,
            detail=detail,
            timestamp=float(self._clock()),
        )
        with self._lock:
            if len(self._events) >= self._max:
                raise OverflowError("shadow audit store full (append-only, no drop)")
            self._events.append(event)
        return event

    def for_shadow(self, shadow_id: str) -> tuple[ShadowAuditEvent, ...]:
        with self._lock:
            return tuple(e for e in self._events if e.shadow_id == shadow_id)

    def chain_kinds(self, shadow_id: str) -> tuple[str, ...]:
        return tuple(e.kind.value for e in self.for_shadow(shadow_id))

    def count(self) -> int:
        with self._lock:
            return len(self._events)

    def snapshot(self) -> tuple[ShadowAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)


__all__ = [
    "SHADOW_AUDIT_CHAIN_ORDER",
    "ShadowAuditEvent",
    "ShadowAuditKind",
    "ShadowAuditStore",
]