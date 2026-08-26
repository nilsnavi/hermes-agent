"""Memory lifecycle state machine.

Each memory record progresses through a bounded lifecycle. The machine is
fail-closed: illegal transitions raise; terminal states are immutable; a
forgotten/retired record can never be revived into a usable state. The lifecycle
is pure bookkeeping — it grants no capability and performs no work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryLifecycleStatus(Enum):
    CREATED = "created"
    ACTIVE = "active"
    CONSOLIDATED = "consolidated"
    FORGOTTEN = "forgotten"
    RETIRED = "retired"


# Legal forward transitions. Terminal states are leaves.
_FORWARD: dict[MemoryLifecycleStatus, frozenset[MemoryLifecycleStatus]] = {
    MemoryLifecycleStatus.CREATED: frozenset(
        {MemoryLifecycleStatus.ACTIVE, MemoryLifecycleStatus.RETIRED}
    ),
    MemoryLifecycleStatus.ACTIVE: frozenset(
        {
            MemoryLifecycleStatus.CONSOLIDATED,
            MemoryLifecycleStatus.FORGOTTEN,
            MemoryLifecycleStatus.RETIRED,
        }
    ),
    MemoryLifecycleStatus.CONSOLIDATED: frozenset(
        {MemoryLifecycleStatus.FORGOTTEN, MemoryLifecycleStatus.RETIRED}
    ),
    MemoryLifecycleStatus.FORGOTTEN: frozenset(),
    MemoryLifecycleStatus.RETIRED: frozenset(),
}

_TERMINAL = frozenset(
    {MemoryLifecycleStatus.FORGOTTEN, MemoryLifecycleStatus.RETIRED}
)


class InvalidMemoryTransition(ValueError):
    """Raised when an illegal memory lifecycle transition is requested."""


@dataclass(frozen=True, slots=True)
class MemoryLifecycleTransition:
    from_status: MemoryLifecycleStatus
    to_status: MemoryLifecycleStatus
    version: int


@dataclass(frozen=True, slots=True)
class MemoryLifecycle:
    status: MemoryLifecycleStatus = MemoryLifecycleStatus.CREATED
    version: int = 0
    history: tuple[MemoryLifecycleTransition, ...] = ()

    def __post_init__(self) -> None:
        if type(self.status) is not MemoryLifecycleStatus:
            raise InvalidMemoryTransition("status must be an exact MemoryLifecycleStatus")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 0:
            raise InvalidMemoryTransition("version must be a non-negative integer")
        for entry in self.history:
            if type(entry) is not MemoryLifecycleTransition:
                raise InvalidMemoryTransition("history must contain lifecycle transitions")

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    def can_transition_to(self, to_status: MemoryLifecycleStatus) -> bool:
        if type(to_status) is not MemoryLifecycleStatus:
            return False
        return to_status in _FORWARD.get(self.status, frozenset())

    def transition(self, to_status: MemoryLifecycleStatus) -> "MemoryLifecycle":
        if type(to_status) is not MemoryLifecycleStatus:
            raise InvalidMemoryTransition("to_status must be an exact MemoryLifecycleStatus")
        if not self.can_transition_to(to_status):
            raise InvalidMemoryTransition(
                f"cannot move memory from {self.status.value} to {to_status.value}"
            )
        next_version = self.version + 1
        transition = MemoryLifecycleTransition(self.status, to_status, next_version)
        return MemoryLifecycle(
            status=to_status,
            version=next_version,
            history=(*self.history, transition),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "version": self.version,
            "history": [
                {
                    "from": t.from_status.value,
                    "to": t.to_status.value,
                    "version": t.version,
                }
                for t in self.history
            ],
        }