"""Sprint 1.3.12 — append-only restart analysis events.

Only analysis events. NO production mutation events exist in this sprint.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .flags import enabled


# Analysis event kinds (append-only).
SERVICE_RESTART_PROFILE_RESOLVED = "SERVICE_RESTART_PROFILE_RESOLVED"
SERVICE_RESTART_ELIGIBILITY_EVALUATED = "SERVICE_RESTART_ELIGIBILITY_EVALUATED"
SERVICE_RESTART_PLAN_CREATED = "SERVICE_RESTART_PLAN_CREATED"
SERVICE_RESTART_SELF_CONTROL_BLOCKED = "SERVICE_RESTART_SELF_CONTROL_BLOCKED"
SERVICE_RESTART_QUIESCENCE_PLANNED = "SERVICE_RESTART_QUIESCENCE_PLANNED"
SERVICE_RESTART_RECOVERY_PLANNED = "SERVICE_RESTART_RECOVERY_PLANNED"
SERVICE_RESTART_EXECUTION_BLOCKED = "SERVICE_RESTART_EXECUTION_BLOCKED"

# Mutation events are deliberately absent.
MUTATION_EVENT_NAMES = ()  # no such events exist

_KNOWN = {
    SERVICE_RESTART_PROFILE_RESOLVED,
    SERVICE_RESTART_ELIGIBILITY_EVALUATED,
    SERVICE_RESTART_PLAN_CREATED,
    SERVICE_RESTART_SELF_CONTROL_BLOCKED,
    SERVICE_RESTART_QUIESCENCE_PLANNED,
    SERVICE_RESTART_RECOVERY_PLANNED,
    SERVICE_RESTART_EXECUTION_BLOCKED,
}


@dataclass
class RestartEvent:
    kind: str
    service_id: str
    seq: int = 0
    detail: str = ""

    @property
    def is_mutation(self) -> bool:
        return any(m in self.kind.upper() for m in ("_EXECUTED", "_STOPPED", "_STARTED"))


class RestartEventLog:
    """In-memory append-only log (shadow/analysis). No persistence in 1.3.12."""

    def __init__(self, *, os_reads: bool = True) -> None:
        self._events: list[RestartEvent] = []
        self._lock = threading.Lock()
        self._seq = 0

    def record(self, kind: str, service_id: str, detail: str = "") -> RestartEvent:
        # Reject unknown / mutation-like kinds by default.
        if kind not in _KNOWN:
            raise ValueError(f"unknown restart event kind: {kind}")
        with self._lock:
            self._seq += 1
            ev = RestartEvent(kind=kind, service_id=service_id,
                              seq=self._seq, detail=detail)
            self._events.append(ev)
            return ev

    def snapshot(self) -> list[RestartEvent]:
        with self._lock:
            return list(self._events)

    def mutation_events(self) -> list[RestartEvent]:
        with self._lock:
            return [e for e in self._events if e.is_mutation]

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


_default_log = RestartEventLog()


def emit(kind: str, service_id: str, detail: str = "") -> RestartEvent:
    """Emit an analysis event to the default log."""
    return _default_log.record(kind, service_id, detail)


def event_log() -> RestartEventLog:
    return _default_log


def mutation_event_count() -> int:
    return len(_default_log.mutation_events())


__all__ = [
    "RestartEvent",
    "RestartEventLog",
    "SERVICE_RESTART_ELIGIBILITY_EVALUATED",
    "SERVICE_RESTART_EXECUTION_BLOCKED",
    "SERVICE_RESTART_PLAN_CREATED",
    "SERVICE_RESTART_PROFILE_RESOLVED",
    "SERVICE_RESTART_QUIESCENCE_PLANNED",
    "SERVICE_RESTART_RECOVERY_PLANNED",
    "SERVICE_RESTART_SELF_CONTROL_BLOCKED",
    "emit",
    "event_log",
    "mutation_event_count",
]