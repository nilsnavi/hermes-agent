"""Sprint 1.3.13 — single aux service restart canary (events)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

# Append-only analysis/execution audit events.
RESTART_PLANNED = "RESTART_CANARY_PLANNED"
RESTART_APPROVED = "RESTART_CANARY_APPROVED"
RESTART_PREFLIGHT_OK = "RESTART_CANARY_PREFLIGHT_OK"
RESTART_ADAPTER_CALL = "RESTART_CANARY_ADAPTER_CALL"
RESTART_OLD_GONE = "RESTART_CANARY_OLD_GONE"
RESTART_QUIESCENT = "RESTART_CANARY_QUIESCENT"
RESTART_NEW_VERIFIED = "RESTART_CANARY_NEW_VERIFIED"
RESTART_STABILIZED = "RESTART_CANARY_STABILIZED"
RESTART_COMMITTED = "RESTART_CANARY_COMMITTED"
RESTART_DUPLICATE = "RESTART_CANARY_DUPLICATE"
RESTART_UNKNOWN_OUTCOME = "RESTART_CANARY_UNKNOWN_OUTCOME"
RESTART_DENIED = "RESTART_CANARY_DENIED"


@dataclass
class RestartEvent:
    kind: str
    service_id: str
    seq: int = 0
    detail: str = ""


class RestartCanaryEventLog:
    def __init__(self) -> None:
        self._events: list[RestartEvent] = []
        self._lock = threading.Lock()
        self._seq = 0

    def record(self, kind: str, service_id: str, detail: str = "") -> RestartEvent:
        with self._lock:
            self._seq += 1
            ev = RestartEvent(kind, service_id, self._seq, detail)
            self._events.append(ev)
            return ev

    def snapshot(self) -> list[RestartEvent]:
        with self._lock:
            return list(self._events)


__all__ = [
    "RESTART_ADAPTER_CALL",
    "RESTART_APPROVED",
    "RESTART_COMMITTED",
    "RESTART_DENIED",
    "RESTART_DUPLICATE",
    "RESTART_NEW_VERIFIED",
    "RESTART_OLD_GONE",
    "RESTART_PLANNED",
    "RESTART_PREFLIGHT_OK",
    "RESTART_QUIESCENT",
    "RESTART_STABILIZED",
    "RESTART_UNKNOWN_OUTCOME",
    "RestartCanaryEventLog",
    "RestartEvent",
]