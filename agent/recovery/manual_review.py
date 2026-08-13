"""Manual review queue (Sprint 1.0.4).

Runs with unknown tool outcomes or failed verification land here. The queue
is in-memory (per recovery process) and every enqueue / resolution is
written to the durable journal (RECOVERY_MANUAL_REVIEW / RECOVERY_REVIEWED)
so the audit trail survives restarts. Resolving only records a human
decision — it never transitions or re-runs anything.
"""

from datetime import datetime
from typing import Callable, Dict, List, Optional

from agent.runtime.events import RuntimeEvent

from .events import RECOVERY_MANUAL_REVIEW, RECOVERY_REVIEWED
from .exceptions import RecoveryErrorBase
from .models import ManualReviewItem


def _utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class ManualReviewQueue:
    """Pending human-review items for ambiguous runs."""

    def __init__(self, store, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._store = store
        self._clock = clock or _utcnow
        self._items: Dict[str, ManualReviewItem] = {}

    def add(
        self,
        run_id: str,
        reason: str,
        disposition: str = "manual_review",
    ) -> ManualReviewItem:
        """Enqueue a run for manual review (idempotent per run)."""
        if run_id in self._items:
            return self._items[run_id]
        item = ManualReviewItem(run_id=run_id, reason=reason, disposition=disposition)
        self._items[run_id] = item
        self._append(RECOVERY_MANUAL_REVIEW, run_id,
                     reason=reason, disposition=disposition)
        return item

    def pending(self) -> List[ManualReviewItem]:
        return [i for i in self._items.values() if not i.resolved]

    def get(self, run_id: str) -> ManualReviewItem:
        try:
            return self._items[run_id]
        except KeyError:
            raise RecoveryErrorBase(f"no manual review item for {run_id}") from None

    def resolve(self, run_id: str, decision: str, note: str = "") -> ManualReviewItem:
        """Record a human decision. Does NOT transition the run."""
        item = self.get(run_id)
        if item.resolved:
            raise RecoveryErrorBase(f"review for {run_id} already resolved")
        item.resolved = True
        item.decision = decision
        item.note = note
        self._append(RECOVERY_REVIEWED, run_id, decision=decision, note=note)
        return item

    def _append(self, event_type: str, run_id: str, **payload) -> None:
        event = RuntimeEvent(
            event_type=event_type,
            run_id=run_id,
            timestamp=self._clock(),
            payload=payload,
        )
        self._store.append_event(event)
