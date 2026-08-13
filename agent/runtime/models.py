"""Agent Run model (Sprint 1.0.1)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from .states import RunStatus


@dataclass
class AgentRun:
    """One agent execution lifecycle.

    ``id`` is immutable by convention (generated once at creation, never
    reassigned); ``status`` is the only field the state machine mutates.
    Plain data with no gateway dependency — serializable via :meth:`to_dict`.
    """

    id: str
    task_type: str
    status: RunStatus
    model_profile: str
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    # Optional TaskContext.to_dict() snapshot (persisted as context_json).
    context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe serialization (ISO-8601 timestamps, status as value)."""
        return {
            "id": self.id,
            "task_type": self.task_type,
            "status": self.status.value,
            "model_profile": self.model_profile,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "result": self.result,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentRun":
        """Rebuild from :meth:`to_dict` output."""
        from .states import RunStatus as _RunStatus

        return cls(
            id=data["id"],
            task_type=data["task_type"],
            status=_RunStatus(data["status"]),
            model_profile=data["model_profile"],
            created_at=_parse_ts(data.get("created_at")),  # type: ignore[arg-type]
            started_at=_parse_ts(data.get("started_at")),
            completed_at=_parse_ts(data.get("completed_at")),
            error=data.get("error"),
            result=data.get("result"),
            context=data.get("context"),
        )


def _parse_ts(value: Optional[str]):
    from datetime import datetime as _dt

    if not value:
        return None
    try:
        return _dt.fromisoformat(value)
    except ValueError:
        return None
