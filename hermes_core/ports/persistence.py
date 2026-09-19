"""Persistence contracts; implementations own SQLite, WAL and migrations."""

from typing import Iterable, Optional, Protocol

from hermes_core.domain.session import Session, SessionId, SessionKey


class SessionRepository(Protocol):
    def create(self, session: Session) -> None: ...
    def get(self, session_id: SessionId) -> Optional[Session]: ...
    def get_by_key(self, key: SessionKey) -> Optional[Session]: ...
    def save(self, session: Session) -> None: ...
    def list_active(self) -> Iterable[Session]: ...


class PersistencePort(Protocol):
    """Application-facing persistence boundary."""

    @property
    def sessions(self) -> SessionRepository: ...
