"""Orchestration result model (Sprint 1.0.5).

``status`` is the RUN row's state machine value; ``stop_reason`` is the
structured explanation of WHY the loop stopped. Together they always
explain the outcome: e.g. (``running``, ``approval_required``) or
(``failed``, ``max_tool_calls``).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .decisions import StopReason


@dataclass
class OrchestrationResult:
    run_id: str
    status: str
    stop_reason: Optional[StopReason] = None
    steps_executed: int = 0
    tool_calls: int = 0
    replans: int = 0
    failures: int = 0
    approvals: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    disposition: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "steps_executed": self.steps_executed,
            "tool_calls": self.tool_calls,
            "replans": self.replans,
            "failures": self.failures,
            "approvals": self.approvals,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "disposition": self.disposition,
            "error": self.error,
            "notes": list(self.notes),
        }

    def summary(self) -> Dict[str, Any]:
        """Observability summary — counts + stop reason, NO tool payloads."""
        elapsed = None
        if self.started_at and self.completed_at:
            try:
                from datetime import datetime

                start = datetime.fromisoformat(self.started_at)
                end = datetime.fromisoformat(self.completed_at)
                elapsed = round(max(0.0, (end - start).total_seconds()), 3)
            except ValueError:
                elapsed = None
        return {
            "run_id": self.run_id,
            "status": self.status,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "steps": self.steps_executed,
            "tool_calls": self.tool_calls,
            "approvals": self.approvals,
            "replans": self.replans,
            "failures": self.failures,
            "elapsed_seconds": elapsed,
        }
