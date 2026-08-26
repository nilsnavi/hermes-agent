"""Abstract lifecycle contract for specialized agents."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .exceptions import AgentContractError
from .models import (
    AgentAnalysis,
    AgentExecutionContext,
    AgentResult,
    AgentTask,
    ValidationResult,
)
from .permissions import AgentPermissions


class BaseAgent(ABC):
    """Base contract implemented by every specialized agent."""

    _IMMUTABLE_CONTRACT_FIELDS = frozenset(
        {"id", "role", "capabilities", "trust_score", "permissions"}
    )

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._IMMUTABLE_CONTRACT_FIELDS and hasattr(self, name):
            raise AttributeError(f"{name} is immutable after initialization")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in self._IMMUTABLE_CONTRACT_FIELDS:
            raise AttributeError(f"{name} is immutable after initialization")
        super().__delattr__(name)

    def __init__(
        self,
        *,
        agent_id: str,
        role: str,
        capabilities: tuple[str, ...],
        trust_score: float,
        permissions: AgentPermissions | None = None,
    ) -> None:
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise AgentContractError("agent_id must be a non-empty string")
        if not isinstance(role, str) or not role.strip():
            raise AgentContractError("role must be a non-empty string")
        if (
            not isinstance(capabilities, tuple)
            or not capabilities
            or any(not isinstance(item, str) or not item.strip() for item in capabilities)
            or len(set(capabilities)) != len(capabilities)
        ):
            raise AgentContractError(
                "capabilities must be a non-empty tuple of unique, non-empty strings"
            )
        if (
            isinstance(trust_score, bool)
            or not isinstance(trust_score, (int, float))
            or not 0.0 <= trust_score <= 1.0
        ):
            raise AgentContractError("trust_score must be between 0 and 1")
        if permissions is not None and type(permissions) is not AgentPermissions:
            raise AgentContractError("permissions must be an AgentPermissions contract")

        self.id = agent_id
        self.role = role
        self.capabilities = capabilities
        self.trust_score = float(trust_score)
        self.permissions = permissions if permissions is not None else AgentPermissions()

    @abstractmethod
    async def analyze(self, task: AgentTask) -> AgentAnalysis:
        """Analyze a task before execution."""

    @abstractmethod
    async def execute(self, context: AgentExecutionContext) -> AgentResult:
        """Execute work within an approved context."""

    @abstractmethod
    async def validate(self, result: AgentResult) -> ValidationResult:
        """Validate an execution result."""
