"""Persistence contracts; implementations own SQLite, WAL and migrations."""

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Protocol

from hermes_core.domain.session import Session, SessionId, SessionKey


class PersistenceStatus(str, Enum):
    SUCCESS = "success"
    CONFLICT = "conflict"
    PERSISTENCE_ERROR = "persistence_error"


@dataclass(frozen=True)
class PersistenceResult:
    status: PersistenceStatus
    session: Optional[Session] = None
    error_code: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.status is PersistenceStatus.SUCCESS


class SessionRepository(Protocol):
    def create(self, session: Session) -> None: ...
    def get(self, session_id: SessionId) -> Optional[Session]: ...
    def get_by_key(self, key: SessionKey) -> Optional[Session]: ...
    def save(self, session: Session) -> None: ...
    def conditional_save(
        self, session: Session, expected_generation: int
    ) -> PersistenceResult: ...
    def list_active(self) -> Iterable[Session]: ...


class PersistencePort(Protocol):
    """Application-facing persistence boundary."""

    @property
    def sessions(self) -> SessionRepository: ...
