from copy import deepcopy

from hermes_core.application.session_service import MutationStatus, SessionService
from hermes_core.domain.session import Session, SessionId, SessionKey, SessionStatus
from hermes_core.ports.persistence import PersistenceResult, PersistenceStatus


class CasRepository:
    def __init__(self, session):
        self.stored = deepcopy(session)
        self.fail = False
        self.adapter_metadata = {"owner": "adapter"}

    def create(self, session):
        self.stored = deepcopy(session)

    def get(self, session_id):
        return deepcopy(self.stored) if session_id == self.stored.session_id else None

    def get_by_key(self, key):
        return deepcopy(self.stored) if key == self.stored.key else None

    def save(self, session):
        self.stored = deepcopy(session)

    def conditional_save(self, session, expected_generation):
        if self.fail:
            return PersistenceResult(PersistenceStatus.PERSISTENCE_ERROR, error_code="io")
        if expected_generation != self.stored.generation:
            return PersistenceResult(PersistenceStatus.CONFLICT)
        self.stored = deepcopy(session)
        return PersistenceResult(PersistenceStatus.SUCCESS, deepcopy(session))

    def list_active(self):
        return [deepcopy(self.stored)] if self.stored.status is SessionStatus.ACTIVE else []


class Persistence:
    def __init__(self, repo):
        self.sessions = repo


def make_service():
    original = Session(SessionId("s"), SessionKey("k"))
    repo = CasRepository(original)
    return original, repo, SessionService(Persistence(repo))


def test_p1_successful_conditional_mutation_advances_generation():
    session, repo, service = make_service()
    result = service.acquire_result(session, "a")
    assert result.status is MutationStatus.SUCCESS
    assert session.generation == 1 and repo.stored.generation == 1
    assert repo.stored.lease_owner == "a"


def test_p2_stale_writer_is_rejected_without_overwrite():
    _, repo, service = make_service()
    a, b = service.resume(SessionId("s")), service.resume(SessionId("s"))
    assert service.acquire_result(a, "a").committed
    stale = service.acquire_result(b, "b")
    assert stale.status is MutationStatus.CONFLICT
    assert repo.stored.lease_owner == "a"


def test_p3_persistence_failure_discards_candidate_and_preserves_source():
    session, repo, service = make_service()
    repo.fail = True
    result = service.acquire_result(session, "a")
    assert result.status is MutationStatus.PERSISTENCE_ERROR
    assert session.lease_owner is None and session.generation == 0
    assert repo.stored.lease_owner is None and repo.stored.generation == 0


def test_release_persistence_failure_preserves_lease():
    session, repo, service = make_service()
    assert service.acquire_result(session, "a").committed
    repo.fail = True
    result = service.release_result(session, "a", 1)
    assert result.status is MutationStatus.PERSISTENCE_ERROR
    assert session.lease_owner == "a" and repo.stored.lease_owner == "a"


def test_close_persistence_failure_preserves_open_session():
    session, repo, service = make_service()
    assert service.acquire_result(session, "a").committed
    repo.fail = True
    result = service.close_result(session, "a", 1)
    assert result.status is MutationStatus.PERSISTENCE_ERROR
    assert session.status is SessionStatus.ACTIVE and repo.stored.status is SessionStatus.ACTIVE


def test_p4_lease_generation_fences_stale_owner():
    _, repo, service = make_service()
    current = service.resume(SessionId("s"))
    assert service.acquire_result(current, "a").committed
    assert service.release_result(current, "a", 1).committed
    assert service.acquire_result(current, "b").committed
    stale = Session(SessionId("s"), SessionKey("k"), generation=2, lease_generation=1, lease_owner="a")
    assert service.release_result(stale, "a", 1).status is MutationStatus.CONFLICT
    assert repo.stored.lease_owner == "b"


def test_p5_stale_release_cannot_overwrite_current_lease():
    _, repo, service = make_service()
    a = service.resume(SessionId("s")); assert service.acquire_result(a, "a").committed
    stale = service.resume(SessionId("s")); assert service.release_result(a, "a", 1).committed
    current = service.resume(SessionId("s")); assert service.acquire_result(current, "b").committed
    assert service.release_result(stale, "a", 1).status is MutationStatus.CONFLICT
    assert repo.stored.lease_owner == "b"


def test_p6_stale_close_cas_cannot_overwrite_newer_session():
    _, repo, service = make_service()
    # Establish a real durable leased state at G=1.
    current = service.resume(SessionId("s"))
    assert service.acquire_result(current, "a").committed

    # Two independent real snapshots of the same durable G=1 state.
    writer = service.resume(SessionId("s"))
    stale = service.resume(SessionId("s"))
    assert writer.generation == 1
    assert stale.generation == 1
    assert stale.lease_owner == "a"
    assert stale.lease_generation == 1

    # First writer advances durable state to G=2.
    assert service.release_result(writer, "a", 1).committed
    assert repo.stored.generation == 2
    assert repo.stored.status is SessionStatus.ACTIVE
    assert repo.stored.lease_owner is None

    # Stale G=1 snapshot is locally valid for close, but CAS rejects it.
    result = service.close_result(stale, "a", 1)
    assert result.status is MutationStatus.CONFLICT
    assert repo.stored.generation == 2
    assert repo.stored.status is SessionStatus.ACTIVE
    assert repo.stored.lease_owner is None
    assert stale.generation == 1
    assert stale.status is SessionStatus.ACTIVE
    assert stale.lease_owner == "a"


def test_p7_rejection_is_distinct_from_cas_conflict():
    session, repo, service = make_service()
    assert service.acquire_result(session, "a").committed
    assert service.acquire_result(session, "b").status is MutationStatus.REJECTED
    stale = Session(SessionId("s"), SessionKey("k"))
    repo.stored.generation = 1
    assert service.acquire_result(stale, "b").status is MutationStatus.CONFLICT


def test_p8_infrastructure_failure_is_distinct_from_conflict():
    session, repo, service = make_service(); repo.fail = True
    assert service.acquire_result(session, "a").status is MutationStatus.PERSISTENCE_ERROR
    repo.fail = False; repo.stored.generation = 4
    assert service.acquire_result(session, "a").status is MutationStatus.CONFLICT


def test_p9_core_owned_fields_round_trip_and_metadata_aliasing():
    session, repo, service = make_service(); session.metadata["x"] = "y"
    session.parent_session_id = SessionId("parent")
    session.acquire_lease("owner")
    service.create(session)
    loaded = service.resume(SessionId("s"))
    assert (loaded.session_id, loaded.key, loaded.status, loaded.generation,
            loaded.lease_generation, loaded.lease_owner, loaded.parent_session_id,
            loaded.metadata) == (session.session_id, session.key, session.status,
                                  session.generation, session.lease_generation,
                                  session.lease_owner, session.parent_session_id,
                                  session.metadata)
    assert loaded.metadata is not repo.stored.metadata
    loaded.metadata["x"] = "changed"
    assert repo.stored.metadata["x"] == "y"


def test_p10_adapter_metadata_is_outside_core_ownership():
    session, repo, service = make_service(); before = deepcopy(repo.adapter_metadata)
    assert service.acquire_result(session, "a").committed
    assert repo.adapter_metadata == before
