"""Runtime events (Sprint 1.0.1) — audit trail for run lifecycle."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

RUN_CREATED = "RUN_CREATED"
STATE_CHANGED = "STATE_CHANGED"
RUN_FAILED = "RUN_FAILED"
RUN_COMPLETED = "RUN_COMPLETED"


@dataclass
class RuntimeEvent:
    """One immutable lifecycle record emitted by the RunEngine."""

    event_type: str
    run_id: str
    timestamp: datetime
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "run_id": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeEvent":
        from datetime import datetime as _dt

        ts = data.get("timestamp")
        try:
            timestamp = _dt.fromisoformat(ts) if ts else None
        except ValueError:
            timestamp = None
        return cls(
            event_type=data["event_type"],
            run_id=data["run_id"],
            timestamp=timestamp,  # type: ignore[arg-type]
            payload=dict(data.get("payload", {})),
        )
