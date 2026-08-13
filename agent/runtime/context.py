"""Task Context (Sprint 1.0.1)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class TaskContext:
    """Description of the agent's task: goal, guardrails, tool surface.

    Pure data — produced by the caller (classifier / planner in later
    sprints), consumed by the runtime for approval decisions and tool gating.
    """

    goal: str
    constraints: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    approval_required: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "constraints": list(self.constraints),
            "allowed_tools": list(self.allowed_tools),
            "metadata": dict(self.metadata),
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskContext":
        """Rebuild from :meth:`to_dict` output (``goal`` is mandatory)."""
        return cls(
            goal=data["goal"],
            constraints=list(data.get("constraints", [])),
            allowed_tools=list(data.get("allowed_tools", [])),
            metadata=dict(data.get("metadata", {})),
            risk_level=data.get("risk_level", "low"),
            approval_required=bool(data.get("approval_required", False)),
        )
