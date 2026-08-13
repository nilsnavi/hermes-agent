"""Gateway V2 structured telemetry events (Sprint 1.0.6).

In-memory ring only — shadow/canary must NOT pollute production
``agent_v2_*`` tables with thousands of rows. Fields are structured
(request_id, mode, eligible, reason, run_id, stop_reason, duration_ms);
prompt bodies and secrets are NEVER recorded.
"""

from collections import deque
from typing import Any, Deque, Dict, List

DECISION = "gateway.v2.decision"
SHADOW_STARTED = "gateway.v2.shadow.started"
SHADOW_COMPLETED = "gateway.v2.shadow.completed"
SHADOW_FAILED = "gateway.v2.shadow.failed"
CANARY_STARTED = "gateway.v2.canary.started"
CANARY_COMPLETED = "gateway.v2.canary.completed"
CANARY_FAILED = "gateway.v2.canary.failed"
FALLBACK_LEGACY = "gateway.v2.fallback.legacy"

EVENT_TYPES = frozenset({
    DECISION, SHADOW_STARTED, SHADOW_COMPLETED, SHADOW_FAILED,
    CANARY_STARTED, CANARY_COMPLETED, CANARY_FAILED, FALLBACK_LEGACY,
})


class V2Telemetry:
    """Lightweight in-memory structured event collector (no prompt bodies)."""

    def __init__(self, max_events: int = 200) -> None:
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max_events)

    def record(self, event_type: str, **fields: Any) -> None:
        entry = {"event": event_type}
        entry.update({k: v for k, v in fields.items() if v is not None})
        self._events.append(entry)

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return list(self._events)[-limit:]

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self._events:
            counts[entry["event"]] = counts.get(entry["event"], 0) + 1
        return counts

    def summary(self) -> Dict[str, Any]:
        return {"counts": self.counts(), "recent": self.recent(10)}
