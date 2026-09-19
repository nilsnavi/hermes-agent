"""Session domain values and lifecycle state."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SessionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass(frozen=True)
class SessionId:
    value: str


@dataclass(frozen=True)
class SessionKey:
    value: str


@dataclass
class Session:
    session_id: SessionId
    key: SessionKey
    generation: int = 0
    status: SessionStatus = SessionStatus.ACTIVE
    lease_owner: Optional[str] = None
    parent_session_id: Optional[SessionId] = None
    metadata: dict[str, str] = field(default_factory=dict)

    def acquire_lease(self, owner: str) -> bool:
        if self.status is not SessionStatus.ACTIVE or self.lease_owner is not None:
            return False
        self.lease_owner = owner
        self.generation += 1
        return True

    def release_lease(self, owner: str, generation: int) -> bool:
        if self.lease_owner != owner or self.generation != generation:
            return False
        self.lease_owner = None
        return True

    def close(self) -> None:
        self.status = SessionStatus.CLOSED
        self.lease_owner = None
