"""Executable C1 contracts for the isolated hermes_core session model."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from hermes_core.application.session_service import SessionService
from hermes_core.domain.session import Session, SessionId, SessionKey, SessionStatus


def make_session() -> Session:
    return Session(session_id=SessionId("session-1"), key=SessionKey("key-1"))


@dataclass
class RecordingSessionRepository:
    by_id: dict[SessionId, Session] = field(default_factory=dict)
    by_key: dict[SessionKey, Session] = field(default_factory=dict)
    saves: list[Session] = field(default_factory=list)

    def create(self, session: Session) -> None:
        self.by_id[session.session_id] = session
        self.by_key[session.key] = session

    def get(self, session_id: SessionId) -> Session | None:
        return self.by_id.get(session_id)

    def get_by_key(self, key: SessionKey) -> Session | None:
        return self.by_key.get(key)

    def save(self, session: Session) -> None:
        self.saves.append(session)

    def list_active(self) -> list[Session]:
        return [session for session in self.by_id.values() if session.status is SessionStatus.ACTIVE]


@dataclass
class RecordingPersistence:
    sessions: RecordingSessionRepository = field(default_factory=RecordingSessionRepository)


def test_session_creation_defaults_to_active_without_a_lease() -> None:
    session = make_session()

    assert session.status is SessionStatus.ACTIVE
    assert session.generation == 0
    assert session.lease_generation == 0
    assert session.lease_owner is None


def test_acquire_allows_only_one_active_lease_and_increments_both_generations() -> None:
    session = make_session()

    assert session.acquire_lease("owner-a") is True
    assert (session.generation, session.lease_generation, session.lease_owner) == (1, 1, "owner-a")

    before_rejected_acquire = (
        session.generation,
        session.lease_generation,
        session.lease_owner,
        session.status,
    )
    assert session.acquire_lease("owner-b") is False
    assert (
        session.generation,
        session.lease_generation,
        session.lease_owner,
        session.status,
    ) == before_rejected_acquire


def test_release_requires_current_owner_and_generation_and_clears_owner() -> None:
    session = make_session()
    assert session.acquire_lease("owner-a") is True

    assert session.release_lease("owner-b", 1) is False
    assert session.release_lease("owner-a", 0) is False
    assert (session.generation, session.lease_generation, session.lease_owner) == (1, 1, "owner-a")

    assert session.release_lease("owner-a", 1) is True
    assert (session.generation, session.lease_generation, session.lease_owner) == (2, 1, None)


@pytest.mark.parametrize("stale_operation", ["release", "close"])
def test_stale_owner_cannot_mutate_a_newer_lease(stale_operation: str) -> None:
    session = make_session()
    assert session.acquire_lease("owner-a") is True
    owner_a_generation = session.lease_generation
    assert session.release_lease("owner-a", owner_a_generation) is True
    assert session.acquire_lease("owner-b") is True

    owner_b_state = (
        session.generation,
        session.lease_generation,
        session.lease_owner,
        session.status,
    )
    if stale_operation == "release":
        changed = session.release_lease("owner-a", owner_a_generation)
    else:
        changed = session.close("owner-a", owner_a_generation)

    assert changed is False
    assert (
        session.generation,
        session.lease_generation,
        session.lease_owner,
        session.status,
    ) == owner_b_state


def test_close_requires_current_owner_and_generation() -> None:
    session = make_session()
    assert session.acquire_lease("owner-a") is True

    assert session.close("owner-b", 1) is False
    assert session.close("owner-a", 0) is False
    assert (session.status, session.lease_owner, session.generation, session.lease_generation) == (
        SessionStatus.ACTIVE,
        "owner-a",
        1,
        1,
    )

    assert session.close("owner-a", 1) is True
    assert (session.status, session.lease_owner, session.generation, session.lease_generation) == (
        SessionStatus.CLOSED,
        None,
        2,
        1,
    )


def test_closed_session_cannot_acquire_a_new_lease() -> None:
    session = make_session()
    assert session.acquire_lease("owner-a") is True
    assert session.close("owner-a", 1) is True
    closed_state = (
        session.status,
        session.lease_owner,
        session.generation,
        session.lease_generation,
    )

    assert session.acquire_lease("owner-b") is False
    assert (
        session.status,
        session.lease_owner,
        session.generation,
        session.lease_generation,
    ) == closed_state


def test_generation_is_monotonic_while_lease_generation_changes_only_on_acquire() -> None:
    session = make_session()
    observed = [(session.generation, session.lease_generation)]

    assert session.acquire_lease("owner-a") is True
    observed.append((session.generation, session.lease_generation))
    assert session.release_lease("owner-a", 1) is True
    observed.append((session.generation, session.lease_generation))
    assert session.acquire_lease("owner-b") is True
    observed.append((session.generation, session.lease_generation))
    assert session.close("owner-b", 2) is True
    observed.append((session.generation, session.lease_generation))

    assert observed == [(0, 0), (1, 1), (2, 1), (3, 2), (4, 2)]
    assert [generation for generation, _ in observed] == sorted(
        generation for generation, _ in observed
    )


def test_session_service_persists_only_successful_lease_transitions() -> None:
    persistence = RecordingPersistence()
    service = SessionService(persistence)
    session = make_session()

    assert service.create(session) is session
    assert service.resume(session.session_id) is session
    assert service.resume_by_key(session.key) is session

    lease_generation = service.acquire(session, "owner-a")
    assert lease_generation == 1
    assert len(persistence.sessions.saves) == 1

    assert service.release(session, "owner-b", lease_generation) is False
    assert len(persistence.sessions.saves) == 1

    assert service.release(session, "owner-a", lease_generation) is True
    assert len(persistence.sessions.saves) == 2


def test_session_service_rejects_second_acquire_without_persisting() -> None:
    persistence = RecordingPersistence()
    service = SessionService(persistence)
    session = make_session()
    service.create(session)
    service.acquire(session, "owner-a")

    with pytest.raises(RuntimeError, match="already owned or closed"):
        service.acquire(session, "owner-b")

    assert len(persistence.sessions.saves) == 1
    assert session.lease_owner == "owner-a"


def test_session_service_reports_missing_sessions() -> None:
    service = SessionService(RecordingPersistence())

    with pytest.raises(LookupError, match="unknown session: missing"):
        service.resume(SessionId("missing"))
    with pytest.raises(LookupError, match="unknown session key: missing-key"):
        service.resume_by_key(SessionKey("missing-key"))
