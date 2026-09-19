"""Session lifecycle orchestration over a persistence port."""

from hermes_core.domain.session import Session, SessionId, SessionKey
from hermes_core.ports.persistence import PersistencePort


class SessionService:
    def __init__(self, persistence: PersistencePort) -> None:
        self._persistence = persistence

    def create(self, session: Session) -> Session:
        self._persistence.sessions.create(session)
        return session

    def resume(self, session_id: SessionId) -> Session:
        session = self._persistence.sessions.get(session_id)
        if session is None:
            raise LookupError(f"unknown session: {session_id.value}")
        return session

    def resume_by_key(self, key: SessionKey) -> Session:
        session = self._persistence.sessions.get_by_key(key)
        if session is None:
            raise LookupError(f"unknown session key: {key.value}")
        return session

    def close(self, session: Session, owner: str, generation: int) -> bool:
        closed = session.close(owner, generation)
        if closed:
            self._persistence.sessions.save(session)
        return closed

    def acquire(self, session: Session, owner: str) -> int:
        if not session.acquire_lease(owner):
            raise RuntimeError("session is already owned or closed")
        self._persistence.sessions.save(session)
        return session.lease_generation

    def release(self, session: Session, owner: str, generation: int) -> bool:
        released = session.release_lease(owner, generation)
        if released:
            self._persistence.sessions.save(session)
        return released
