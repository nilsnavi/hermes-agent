"""Bounded owner/no-owner parity against the real durable turn-lease table.

No epoch or TTL mapping is inferred from the core's default fields.
"""

from contextlib import closing
import os
import sqlite3

import pytest

from hermes_core.domain.session import Session, SessionId, SessionKey


@pytest.fixture
def lease_store(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    from hermes_state import SessionDB

    path = tmp_path / "lease-state.db"
    db = SessionDB(path)
    try:
        db.create_session("session", "test", session_key="key", profile_name="offline")
        yield db, path
    finally:
        db.close()


def read_lease(path):
    # Observation only: all fixture mutations go through real SessionDB APIs.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT conversation_id, holder, acquired_at, expires_at "
            "FROM session_turn_leases WHERE conversation_id = ?", ("session",)
        ).fetchone()
        return dict(row) if row is not None else None


def core_session(db):
    row = db.get_session("session")
    assert row["ended_at"] is None
    return Session(SessionId(row["id"]), SessionKey(row["session_key"]))


def test_sp3_real_durable_holder_matches_core_exclusive_owner(lease_store):
    db, path = lease_store
    core = core_session(db)
    owner = f"pid={os.getpid()}:turn=offline-owner"
    competitor = f"pid={os.getpid()}:turn=offline-competitor"
    assert db.try_acquire_session_turn_lease("session", owner, ttl_seconds=300)
    assert core.acquire_lease(owner)
    observed = read_lease(path)
    assert observed["conversation_id"] == core.session_id.value
    assert observed["holder"] == core.lease_owner == owner
    assert observed["expires_at"] - observed["acquired_at"] == pytest.approx(300)
    assert not db.try_acquire_session_turn_lease("session", competitor, ttl_seconds=300)
    assert not core.acquire_lease(competitor)
    db.release_session_turn_lease("session", competitor)
    assert not core.release_lease(competitor, core.lease_generation)
    assert read_lease(path) == observed
    assert core.lease_owner == observed["holder"]
    db.release_session_turn_lease("session", owner)


def test_sp6_real_absent_and_released_lease_matches_core_unowned(lease_store):
    db, path = lease_store
    core = core_session(db)
    assert read_lease(path) is None and core.lease_owner is None
    owner = f"pid={os.getpid()}:turn=offline-owner"
    assert db.try_acquire_session_turn_lease("session", owner, ttl_seconds=300)
    assert core.acquire_lease(owner)
    assert read_lease(path)["holder"] == core.lease_owner == owner
    db.release_session_turn_lease("session", owner)
    assert core.release_lease(owner, core.lease_generation)
    assert read_lease(path) is None and core.lease_owner is None
    assert not db.refresh_session_turn_lease("session", owner, ttl_seconds=300)
    db.release_session_turn_lease("session", owner)
    assert read_lease(path) is None
    assert db.get_session("session")["ended_at"] is None
