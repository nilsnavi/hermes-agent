"""Execution budget (Sprint 1.0.5) — durable, journal-derived counters.

The budget is NOT a Python counter: every metric is derived from the
durable event journal, so a process restart can never reset it.

- steps       = COUNT(STEP_STARTED)
- tool_calls  = COUNT(TOOL_STARTED)
- failures    = COUNT(TOOL_FAILED)
- replans     = COUNT(REPLAN_REQUESTED)
- elapsed     = clock() − run.started_at  (original start, not this process)

Each ``check_*`` raises :class:`BudgetExceeded` with the limit name when
the budget is exhausted; the orchestrator maps it to a StopReason.
"""

from datetime import datetime
from typing import Callable, Optional

from agent.execution.events import STEP_STARTED, TOOL_FAILED, TOOL_STARTED
from agent.runtime.events import RuntimeEvent

from .decisions import StopReason
from .events import REPLAN_REQUESTED
from .exceptions import BudgetExceeded
from .policy import ExecutionPolicy

_LIMIT_TO_REASON = {
    "steps": StopReason.MAX_STEPS,
    "tool_calls": StopReason.MAX_TOOL_CALLS,
    "replans": StopReason.MAX_REPLANS,
    "failures": StopReason.MAX_FAILURES,
    "runtime": StopReason.RUNTIME_TIMEOUT,
}


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class ExecutionBudget:
    """Live, journal-derived budget for one run."""

    def __init__(
        self,
        policy: ExecutionPolicy,
        store,
        run_id: str,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._policy = policy
        self._store = store
        self._run_id = run_id
        self._clock = clock or _utcnow
        self._started_at: Optional[datetime] = None

    # ── durable counters (journal-derived) ───────────────────────────

    @property
    def _events(self) -> list:
        return self._store.list_events(run_id=self._run_id)

    @staticmethod
    def _count(events, event_type: str) -> int:
        return sum(1 for e in events if e.event_type == event_type)

    @property
    def steps(self) -> int:
        return self._count(self._events, STEP_STARTED)

    @property
    def tool_calls(self) -> int:
        return self._count(self._events, TOOL_STARTED)

    @property
    def failures(self) -> int:
        return self._count(self._events, TOOL_FAILED)

    @property
    def replans(self) -> int:
        return self._count(self._events, REPLAN_REQUESTED)

    def set_started_at(self, started_at: Optional[datetime]) -> None:
        self._started_at = started_at

    @property
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, (self._clock() - self._started_at).total_seconds())

    # ── checks (raise BudgetExceeded) ────────────────────────────────

    def check_step(self) -> None:
        if self.steps >= self._policy.max_steps:
            raise BudgetExceeded("steps")

    def check_tool_call(self) -> None:
        if self.tool_calls >= self._policy.max_tool_calls:
            raise BudgetExceeded("tool_calls")

    def check_replan(self) -> None:
        if self.replans >= self._policy.max_replans:
            raise BudgetExceeded("replans")

    def check_failure(self) -> None:
        if self.failures >= self._policy.max_failures:
            raise BudgetExceeded("failures")

    def check_time(self) -> None:
        if (
            self._started_at is not None
            and self.elapsed_seconds > self._policy.max_runtime_seconds
        ):
            raise BudgetExceeded("runtime")

    def stop_reason_for(self, exc: BudgetExceeded) -> StopReason:
        return _LIMIT_TO_REASON.get(exc.limit, StopReason.EXECUTION_FAILED)


def stop_reason_for_limit(limit: str) -> StopReason:
    return _LIMIT_TO_REASON.get(limit, StopReason.EXECUTION_FAILED)
