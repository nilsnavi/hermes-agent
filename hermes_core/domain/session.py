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
    """
    Domain model for Hermes session lifecycle.

    generation:
        Version of session state changes.

    lease_generation:
        Version of ownership lease.
        Used to prevent stale workers from modifying session state.
    """

    session_id: SessionId
    key: SessionKey

    # Session state version
    generation: int = 0

    # Lease ownership version
    lease_generation: int = 0

    status: SessionStatus = SessionStatus.ACTIVE

    # Current lease owner
    lease_owner: Optional[str] = None

    parent_session_id: Optional[SessionId] = None

    metadata: dict[str, str] = field(default_factory=dict)

    def acquire_lease(self, owner: str) -> bool:
        """
        Acquire session ownership lease.

        Only one owner can hold a lease at the same time.
        """

        if self.status is not SessionStatus.ACTIVE or self.lease_owner is not None:
            return False

        self.lease_owner = owner

        # New ownership generation
        self.lease_generation += 1

        # Session state changed
        self.generation += 1

        return True

    def release_lease(self, owner: str, lease_generation: int) -> bool:
        """
        Release lease only by current owner.

        Prevents stale workers from releasing a newer lease.
        """

        if (
            self.lease_owner != owner
            or self.lease_generation != lease_generation
        ):
            return False

        self.lease_owner = None

        self.generation += 1

        return True

    def close(self, owner: str, lease_generation: int) -> bool:
        """
        Close session only by current lease owner.

        Stale owners cannot close active sessions.
        """

        if (
            self.lease_owner != owner
            or self.lease_generation != lease_generation
        ):
            return False

        self.status = SessionStatus.CLOSED
        self.lease_owner = None

        self.generation += 1

        return True
