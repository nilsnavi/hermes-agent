"""Session lifecycle orchestration over a persistence port."""

from copy import deepcopy
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

from hermes_core.domain.session import Session, SessionId, SessionKey
from hermes_core.ports.persistence import (
    PersistencePort,
    PersistenceResult,
    PersistenceStatus,
)


class MutationStatus(str, Enum):
    SUCCESS = "success"
    CONFLICT = "conflict"
    REJECTED = "rejected"
    PERSISTENCE_ERROR = "persistence_error"


@dataclass(frozen=True)
class SessionMutationResult:
    status: MutationStatus
    session: Optional[Session] = None
    generation: Optional[int] = None
    reason: Optional[str] = None

    @property
    def committed(self) -> bool:
        return self.status is MutationStatus.SUCCESS


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
        return self.close_result(session, owner, generation).committed

    def acquire(self, session: Session, owner: str) -> int:
        result = self.acquire_result(session, owner)
        if result.status is MutationStatus.SUCCESS:
            return session.lease_generation
        if result.status is MutationStatus.REJECTED:
            raise RuntimeError("session is already owned or closed")
        raise RuntimeError("session persistence failed")

    def release(self, session: Session, owner: str, generation: int) -> bool:
        return self.release_result(session, owner, generation).committed

    @staticmethod
    def _candidate(session: Session) -> Session:
        return replace(session, metadata=deepcopy(session.metadata))

    @staticmethod
    def _adopt(target: Session, candidate: Session) -> None:
        target.generation = candidate.generation
        target.lease_generation = candidate.lease_generation
        target.status = candidate.status
        target.lease_owner = candidate.lease_owner
        target.parent_session_id = candidate.parent_session_id
        target.metadata = deepcopy(candidate.metadata)

    def _persist(self, candidate: Session, expected: int) -> PersistenceResult:
        method = getattr(self._persistence.sessions, "conditional_save", None)
        if method is None:
            return PersistenceResult(
                PersistenceStatus.PERSISTENCE_ERROR,
                error_code="conditional_save_not_supported",
            )
        try:
            result = method(candidate, expected)
        except Exception:
            return PersistenceResult(
                PersistenceStatus.PERSISTENCE_ERROR,
                error_code="persistence_error",
            )
        if not isinstance(result, PersistenceResult):
            return PersistenceResult(
                PersistenceStatus.PERSISTENCE_ERROR,
                error_code="invalid_persistence_result",
            )
        return result

    def _transition(self, session: Session, transition) -> SessionMutationResult:
        expected = session.generation
        candidate = self._candidate(session)
        if not transition(candidate):
            return SessionMutationResult(
                MutationStatus.REJECTED, reason="domain_rejected"
            )
        persisted = self._persist(candidate, expected)
        if persisted.status is PersistenceStatus.CONFLICT:
            return SessionMutationResult(MutationStatus.CONFLICT, reason="stale_generation")
        if persisted.status is PersistenceStatus.PERSISTENCE_ERROR:
            return SessionMutationResult(
                MutationStatus.PERSISTENCE_ERROR, reason=persisted.error_code
            )
        if persisted.session is None:
            return SessionMutationResult(
                MutationStatus.PERSISTENCE_ERROR, reason="missing_committed_session"
            )
        self._adopt(session, persisted.session)
        return SessionMutationResult(
            MutationStatus.SUCCESS, session=session, generation=session.generation
        )

    def acquire_result(self, session: Session, owner: str) -> SessionMutationResult:
        return self._transition(session, lambda candidate: candidate.acquire_lease(owner))

    def release_result(
        self, session: Session, owner: str, generation: int
    ) -> SessionMutationResult:
        return self._transition(
            session, lambda candidate: candidate.release_lease(owner, generation)
        )

    def close_result(
        self, session: Session, owner: str, generation: int
    ) -> SessionMutationResult:
        return self._transition(session, lambda candidate: candidate.close(owner, generation))
