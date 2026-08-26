"""Worker health record (Phase 8.3 §13).

Health is observability-only and explicitly *not* authority: nothing here can
change production, restart a service, or signal anything.  It is a bounded,
informational snapshot an Operator can read.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .lifecycle import WorkerLifecycle


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    lifecycle: WorkerLifecycle
    state_since: float
    envelopes_processed: int
    queue_depth: int
    last_error: str = ""

    def is_ok(self) -> bool:
        return self.lifecycle is WorkerLifecycle.HEALTHY


class WorkerHealth:
    """Informational health tracker (never production authority)."""

    __slots__ = ("_lifecycle", "_since", "_processed", "_last_error", "_lock")

    def __init__(self, lifecycle: WorkerLifecycle = WorkerLifecycle.STOPPED) -> None:
        self._lifecycle = lifecycle
        self._since = time.time()
        self._processed = 0
        self._last_error = ""
        self._lock = threading.Lock()

    def set_lifecycle(self, value: WorkerLifecycle) -> None:
        if type(value) is not WorkerLifecycle:
            raise ValueError("lifecycle must be an exact WorkerLifecycle value")
        lock = self._lock
        lock.acquire()
        try:
            self._lifecycle = value
            self._since = time.time()
        finally:
            lock.release()

    def bump_processed(self, delta: int = 1) -> None:
        with self._lock:
            self._processed += delta

    def record_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message[:512]

    def snapshot(self, queue_depth: int = 0) -> HealthSnapshot:
        with self._lock:
            return HealthSnapshot(
                lifecycle=self._lifecycle,
                state_since=self._since,
                envelopes_processed=self._processed,
                queue_depth=queue_depth,
                last_error=self._last_error,
            )


__all__ = ["HealthSnapshot", "WorkerHealth"]