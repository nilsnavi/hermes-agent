"""Agent coordination state machine.

Models the orchestration-level progression of a coordinated task across agents:
from analysis through planning, routing, execution supervision, validation, and
terminal outcomes. It is a pure state machine used by the control plane to
decide which orchestration phase is legal next. It owns no execution authority
and never dispatches; it only tracks phase legality.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CoordinationStatus(Enum):
    ANALYZING = "analyzing"
    PLANNING = "planning"
    ROUTING = "routing"
    SUPERVISING = "supervising"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Legal forward transitions. Terminal states are leaves.
_FORWARD: dict[CoordinationStatus, frozenset[CoordinationStatus]] = {
    CoordinationStatus.ANALYZING: frozenset({CoordinationStatus.PLANNING, CoordinationStatus.FAILED}),
    CoordinationStatus.PLANNING: frozenset({CoordinationStatus.ROUTING, CoordinationStatus.FAILED}),
    CoordinationStatus.ROUTING: frozenset({CoordinationStatus.SUPERVISING, CoordinationStatus.FAILED}),
    CoordinationStatus.SUPERVISING: frozenset({CoordinationStatus.VALIDATING, CoordinationStatus.FAILED, CoordinationStatus.CANCELLED}),
    CoordinationStatus.VALIDATING: frozenset({CoordinationStatus.COMPLETED, CoordinationStatus.FAILED}),
    CoordinationStatus.COMPLETED: frozenset(),
    CoordinationStatus.FAILED: frozenset(),
    CoordinationStatus.CANCELLED: frozenset(),
}

_TERMINAL = frozenset(
    {CoordinationStatus.COMPLETED, CoordinationStatus.FAILED, CoordinationStatus.CANCELLED}
)


class InvalidCoordinationTransition(ValueError):
    """Raised when an illegal coordination transition is requested."""


@dataclass(frozen=True, slots=True)
class CoordinationTransition:
    from_status: CoordinationStatus
    to_status: CoordinationStatus
    version: int


@dataclass(frozen=True, slots=True)
class CoordinationState:
    status: CoordinationStatus = CoordinationStatus.ANALYZING
    version: int = 0
    history: tuple[CoordinationTransition, ...] = ()

    def __post_init__(self) -> None:
        if type(self.status) is not CoordinationStatus:
            raise InvalidCoordinationTransition("status must be an exact CoordinationStatus")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 0:
            raise InvalidCoordinationTransition("version must be a non-negative integer")
        for entry in self.history:
            if type(entry) is not CoordinationTransition:
                raise InvalidCoordinationTransition("history must contain coordination transitions")

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    def can_transition_to(self, to_status: CoordinationStatus) -> bool:
        if type(to_status) is not CoordinationStatus:
            return False
        return to_status in _FORWARD.get(self.status, frozenset())

    def transition(self, to_status: CoordinationStatus) -> "CoordinationState":
        if type(to_status) is not CoordinationStatus:
            raise InvalidCoordinationTransition("to_status must be an exact CoordinationStatus")
        if not self.can_transition_to(to_status):
            raise InvalidCoordinationTransition(
                f"cannot coordinate from {self.status.value} to {to_status.value}"
            )
        next_version = self.version + 1
        new_transition = CoordinationTransition(self.status, to_status, next_version)
        return CoordinationState(
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