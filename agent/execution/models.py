"""Execution plan models (Sprint 1.0.2)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class StepStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionStep:
    """One unit of work in an execution plan."""

    id: str
    name: str
    description: str
    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "requires_approval": self.requires_approval,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionStep":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            tool=data["tool"],
            arguments=dict(data.get("arguments", {})),
            requires_approval=bool(data.get("requires_approval", False)),
            status=StepStatus(data.get("status", StepStatus.PENDING.value)),
            result=data.get("result"),
            error=data.get("error"),
        )


@dataclass
class ExecutionPlan:
    """Ordered list of steps derived from a TaskContext goal."""

    id: str
    run_id: str
    goal: str
    steps: List[ExecutionStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.CREATED
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def step(self, step_id: str) -> Optional[ExecutionStep]:
        return next((s for s in self.steps if s.id == step_id), None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPlan":
        return cls(
            id=data["id"],
            run_id=data["run_id"],
            goal=data["goal"],
            steps=[ExecutionStep.from_dict(s) for s in data.get("steps", [])],
            status=PlanStatus(data.get("status", PlanStatus.CREATED.value)),
            created_at=_parse_ts(data.get("created_at")),
            started_at=_parse_ts(data.get("started_at")),
            completed_at=_parse_ts(data.get("completed_at")),
            metadata=dict(data.get("metadata", {})),
        )


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
