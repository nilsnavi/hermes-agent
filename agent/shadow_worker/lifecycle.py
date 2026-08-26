"""Worker lifecycle state machine (Phase 8.3 §13).

Health/lifecycle is INFORMATIONAL ONLY: it is a label the worker publishes for
observability and Operator review.  It is never production authority and it can
never mutate production.  A worker may be DEGRADED/FAILED and production simply
continues unworried.
"""

from __future__ import annotations

import threading
from enum import Enum


class WorkerLifecycle(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPING = "stopping"


#: Allowed transitions (closed, deterministic).
_TRANSITIONS: dict[WorkerLifecycle, frozenset[WorkerLifecycle]] = {
    WorkerLifecycle.STOPPED: frozenset({WorkerLifecycle.STARTING}),
    WorkerLifecycle.STARTING: frozenset(
        {WorkerLifecycle.HEALTHY, WorkerLifecycle.DEGRADED, WorkerLifecycle.FAILED,
         WorkerLifecycle.STOPPING}
    ),
    WorkerLifecycle.HEALTHY: frozenset(
        {WorkerLifecycle.DEGRADED, WorkerLifecycle.FAILED, WorkerLifecycle.STOPPING}
    ),
    WorkerLifecycle.DEGRADED: frozenset(
        {WorkerLifecycle.HEALTHY, WorkerLifecycle.FAILED, WorkerLifecycle.STOPPING}
    ),
    WorkerLifecycle.FAILED: frozenset({WorkerLifecycle.STOPPED, WorkerLifecycle.STOPPING}),
    WorkerLifecycle.STOPPING: frozenset({WorkerLifecycle.STOPPED}),
}


class WorkerLifecycleError(ValueError):
    pass


class WorkerLifecycleState:
    """Thread-safe lifecycle holder with validated transitions."""

    __slots__ = ("_state", "_lock")

    def __init__(self, initial: WorkerLifecycle = WorkerLifecycle.STOPPED) -> None:
        if type(initial) is not WorkerLifecycle:
            raise WorkerLifecycleError("initial must be an exact WorkerLifecycle value")
        self._state = initial
        self._lock = threading.Lock()

    @property
    def state(self) -> WorkerLifecycle:
        return self._state

    def transition(self, target: WorkerLifecycle) -> WorkerLifecycle:
        """Advance to ``target`` iff it is a permitted transition; else raise."""
        if type(target) is not WorkerLifecycle:
            raise WorkerLifecycleError("target must be an exact WorkerLifecycle value")
        lock = self._lock
        lock.acquire()
        try:
            if target not in _TRANSITIONS[self._state]:
                raise WorkerLifecycleError(
                    f"invalid lifecycle transition {self._state.value!r} -> {target.value!r}"
                )
            self._state = target
            return target
        finally:
            lock.release()

    def is_healthy(self) -> bool:
        return self._state is WorkerLifecycle.HEALTHY

    def informational(self) -> str:
        """Observability-only representation; never an instruction."""
        return self._state.value


__all__ = [
    "WorkerLifecycle",
    "WorkerLifecycleError",
    "WorkerLifecycleState",
]