"""Recovery scanner (Sprint 1.0.4) — find + classify incomplete runs.

Read-only pass over ``agent_v2_runs``: every non-terminal run is loaded
with its journal, classified, and reported. Nothing is executed or
transitioned here; the scan writes ONE audit event per run
(``RECOVERY_SCANNED`` / ``RECOVERY_CLASSIFIED``).
"""

from datetime import datetime
from typing import Callable, List, Optional

from agent.persistence.recovery import RecoveryDisposition
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun

from .classifier import RecoveryClassifier
from .events import RECOVERY_CLASSIFIED, RECOVERY_SCANNED, RECOVERY_SKIPPED
from .models import RunRecoveryResult


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class RecoveryScanner:
    """Scan the durable store for runs that need a recovery decision."""

    def __init__(self, store, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._store = store
        self._clock = clock or _utcnow
        self._classifier = RecoveryClassifier(store)

    def scan(self, audit: bool = True) -> List[RunRecoveryResult]:
        """Classify every incomplete run; return results in store order.

        *audit=True* appends RECOVERY_SCANNED + RECOVERY_CLASSIFIED events
        to the journal (one boundary per run — atomic).
        """
        results: List[RunRecoveryResult] = []
        for run in self._store.list_incomplete_runs():
            events: List[RuntimeEvent] = self._store.list_events(run_id=run.id)
            disposition = self._classifier.classify_run_with_events(run, events)
            action = _action_for(run, disposition)
            result = RunRecoveryResult(
                run_id=run.id,
                run_status=run.status.value,
                disposition=disposition.value,
                action=action,
                event_count=len(events),
            )
            if audit:
                self._append_scan_events(run.id, disposition, action, len(events))
            results.append(result)
        return results

    def _append_scan_events(
        self,
        run_id: str,
        disposition: RecoveryDisposition,
        action: str,
        event_count: int,
    ) -> None:
        now = self._clock()
        scanned = RuntimeEvent(
            event_type=RECOVERY_SCANNED,
            run_id=run_id,
            timestamp=now,
            payload={"disposition": disposition.value, "action": action},
        )
        classified = RuntimeEvent(
            event_type=RECOVERY_CLASSIFIED,
            run_id=run_id,
            timestamp=now,
            payload={
                "disposition": disposition.value,
                "action": action,
                "event_count": event_count,
            },
        )
        with self._store.transaction():
            self._store.append_event(scanned)
            self._store.append_event(classified)


def _action_for(run: AgentRun, disposition: RecoveryDisposition) -> str:
    """Default action label per disposition (used by scan reports)."""
    if disposition is RecoveryDisposition.TERMINAL:
        return "ignore"
    if disposition is RecoveryDisposition.SAFE_TO_RESUME:
        return "resume"
    if disposition is RecoveryDisposition.WAIT_FOR_APPROVAL:
        return "wait"
    if disposition is RecoveryDisposition.REQUIRES_VERIFICATION:
        return "verify"
    return "manual_review"
