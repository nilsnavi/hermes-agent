"""Run Engine — lifecycle manager (Sprint 1.0.1).

Owns run creation, status transitions, timestamp bookkeeping and the runtime
event trail. Clock and event sink are injectable for deterministic tests.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .events import (
    RUN_COMPLETED,
    RUN_CREATED,
    RUN_FAILED,
    STATE_CHANGED,
    RuntimeEvent,
)
from .models import AgentRun
from .state_machine import transition
from .states import RunStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunEngine:
    """Create and drive :class:`AgentRun` lifecycles.

    Every status change goes through the deterministic state machine —
    forbidden transitions raise InvalidStateTransition (fail closed).
    Each lifecycle action is recorded in ``events`` for the audit trail.
    """

    def __init__(
        self,
        clock: Optional[Callable[[], datetime]] = None,
        events: Optional[List[RuntimeEvent]] = None,
        store=None,
    ) -> None:
        self._clock = clock or _utcnow
        self._events: List[RuntimeEvent] = events if events is not None else []
        self._seq = 0
        # Optional durable store (Sprint 1.0.3): object exposing
        # save_run/update_run/append_event. Default None = memory-only,
        # full backward compatibility. Production gateway does NOT use it.
        self._store = store

    @property
    def events(self) -> List[RuntimeEvent]:
        """Immutable-by-convention audit trail (caller may still read it)."""
        return self._events

    # ── lifecycle ────────────────────────────────────────────────────

    def create_run(
        self,
        task_type: str,
        model_profile: str,
        run_id: Optional[str] = None,
    ) -> AgentRun:
        """Create a run in CREATED state and emit RUN_CREATED."""
        run = AgentRun(
            id=run_id or self._next_id(),
            task_type=task_type,
            status=RunStatus.CREATED,
            model_profile=model_profile,
            created_at=self._clock(),
        )
        event = self._emit(
            RUN_CREATED, run, task_type=task_type, model_profile=model_profile
        )
        if self._store is not None:
            self._store.save_run(run)
            self._store.append_event(event)
        return run

    def start_run(self, run) -> AgentRun:
        """CREATED -> CLASSIFYING: begin the classification phase."""
        return self._transition(run, RunStatus.CLASSIFYING)

    def complete_run(
        self, run, result: Optional[Dict[str, Any]] = None
    ) -> AgentRun:
        """VERIFYING -> COMPLETED: the only legal success terminal."""
        self._transition(run, RunStatus.COMPLETED)
        run.result = result
        run.completed_at = self._clock()
        event = self._emit(RUN_COMPLETED, run, result=result)
        if self._store is not None:
            self._store.update_run(run)
            self._store.append_event(event)
        return run

    def fail_run(self, run, error: Optional[str] = None) -> AgentRun:
        """Any active state -> FAILED: record the failure, terminal."""
        self._transition(run, RunStatus.FAILED)
        run.error = error
        event = self._emit(RUN_FAILED, run, error=error)
        if self._store is not None:
            self._store.update_run(run)
            self._store.append_event(event)
        return run

    def cancel_run(self, run) -> AgentRun:
        """Any active state -> CANCELLED: operator abort, terminal."""
        return self._transition(run, RunStatus.CANCELLED)

    def transition(self, run, target: RunStatus) -> AgentRun:
        """Generic explicit transition through the state machine."""
        return self._transition(run, target)

    # ── internals ────────────────────────────────────────────────────

    def _transition(self, run, target: RunStatus) -> AgentRun:
        prev = run.status
        transition(run, target)  # raises InvalidStateTransition when illegal
        if run.status is RunStatus.RUNNING and run.started_at is None:
            run.started_at = self._clock()
        if run.status is RunStatus.COMPLETED and run.completed_at is None:
            run.completed_at = self._clock()
        event = self._emit(
            STATE_CHANGED, run, from_status=prev.value, to_status=target.value
        )
        if self._store is not None:
            self._store.update_run(run)
            self._store.append_event(event)
        return run

    def _emit(self, event_type: str, run, **payload: Any) -> RuntimeEvent:
        event = RuntimeEvent(
            event_type=event_type,
            run_id=run.id,
            timestamp=self._clock(),
            payload=payload,
        )
        self._events.append(event)
        return event

    def _next_id(self) -> str:
        self._seq += 1
        return f"run_{self._clock().strftime('%Y%m%d%H%M%S%f')}_{self._seq}"
