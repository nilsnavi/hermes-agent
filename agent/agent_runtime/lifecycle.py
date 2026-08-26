"""Agent lifecycle state machine.

Describes the durable lifecycle of a registered agent definition. This is a
pure state machine modelled on the frozen registry: it decides which states a
registered agent may move between and rejects every other transition (fail
closed). It holds no execution authority — an agent's lifecycle state never
grants the ability to run a tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .exceptions import AgentContractError


class AgentLifecycleStatus(Enum):
    REGISTERED = "registered"
    READY = "ready"
    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRED = "retired"


# Legal forward transitions. Terminal states (RETIRED, DISABLED) are leaves.
_FORWARD = {
    AgentLifecycleStatus.REGISTERED: frozenset({AgentLifecycleStatus.READY}),
    AgentLifecycleStatus.READY: frozenset(
        {AgentLifecycleStatus.ACTIVE, AgentLifecycleStatus.RETIRED}
    ),
    AgentLifecycleStatus.ACTIVE: frozenset(
        {AgentLifecycleStatus.DISABLED, AgentLifecycleStatus.RETIRED}
    ),
    AgentLifecycleStatus.DISABLED: frozenset({AgentLifecycleStatus.RETIRED}),
    AgentLifecycleStatus.RETIRED: frozenset(),
}

_TERMINAL = frozenset({AgentLifecycleStatus.RETIRED, AgentLifecycleStatus.DISABLED})
# A disabled agent may be re-enabled only through the registry re-versioning
# path, not by a direct lifecycle transition (fail-closed; no flapping).


@dataclass(frozen=True, slots=True)
class AgentLifecycleTransition:
    from_status: AgentLifecycleStatus
    to_status: AgentLifecycleStatus
    version: int


@dataclass(frozen=True, slots=True)
class AgentLifecycle:
    status: AgentLifecycleStatus = AgentLifecycleStatus.REGISTERED
    version: int = 0
    history: tuple[AgentLifecycleTransition, ...] = ()

    def __post_init__(self) -> None:
        if type(self.status) is not AgentLifecycleStatus:
            raise AgentContractError("status must be an exact AgentLifecycleStatus")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 0:
            raise AgentContractError("version must be a non-negative integer")
        for entry in self.history:
            if type(entry) is not AgentLifecycleTransition:
                raise AgentContractError("history must contain lifecycle transitions")

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    def can_transition_to(self, to_status: AgentLifecycleStatus) -> bool:
        if type(to_status) is not AgentLifecycleStatus:
            return False
        return to_status in _FORWARD.get(self.status, frozenset())

    def transition(self, to_status: AgentLifecycleStatus) -> "AgentLifecycle":
        """Return the next lifecycle state, or raise on an illegal transition."""
        if type(to_status) is not AgentLifecycleStatus:
            raise AgentContractError("to_status must be an exact AgentLifecycleStatus")
        if not self.can_transition_to(to_status):
            raise AgentContractError(
                f"cannot transition agent from {self.status.value} to {to_status.value}"
            )
        next_version = self.version + 1
        new_transition = AgentLifecycleTransition(self.status, to_status, next_version)
        return AgentLifecycle(
            status=to_status,
            version=next_version,
            history=(*self.history, new_transition),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "version": self.version,
            "history": [
                {
                    "from_status": t.from_status.value,
                    "to_status": t.to_status.value,
                    "version": t.version,
                }
                for t in self.history
            ],
        }