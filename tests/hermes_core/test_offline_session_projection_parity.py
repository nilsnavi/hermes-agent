"""Phase-0 legacy-to-core session projection checks.

The legacy import is deliberately lazy: this file must never make collection
touch a user's Hermes home. A missing supported dependency skips the legacy
slice instead of manufacturing provenance from a fake row.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

import pytest

from hermes_core.domain.session import Session, SessionId, SessionKey, SessionStatus


@pytest.fixture(autouse=True)
def isolated_legacy_home(tmp_path, monkeypatch):
    # --confcutdir excludes the repository-wide home isolation fixture.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))


def project_detached(legacy_row: dict) -> tuple[Session, dict[str, object]]:
    """Project only fields owned by the detached core model.

    Adapter-owned legacy data is returned in a separate deep-copied envelope.
    This helper intentionally accepts a row already loaded by the authoritative
    legacy representation; it is not a replacement legacy schema.
    """
    session_id = legacy_row.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("missing_required_identity")
    ended_at = legacy_row.get("ended_at")
    if ended_at is not None and not isinstance(ended_at, (int, float)):
        raise ValueError("malformed_lifecycle")
    core = Session(
        SessionId(session_id),
        SessionKey(legacy_row.get("session_key") or session_id),
        status=SessionStatus.ACTIVE if ended_at is None else SessionStatus.CLOSED,
        parent_session_id=(SessionId(legacy_row["parent_session_id"])
                           if legacy_row.get("parent_session_id") else None),
        metadata={"source": legacy_row.get("source", "")},
    )
    adapter = deepcopy({
        key: value for key, value in legacy_row.items()
        if key not in {"id", "session_key", "parent_session_id", "source"}
    })
    return core, adapter


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy_db_or_skip(tmp_path: Path):
    try:
        from hermes_state import SessionDB
    except ModuleNotFoundError as exc:
        pytest.skip(f"legacy SessionDB unavailable: {exc.name}")
    path = tmp_path / "synthetic-state.db"
    writer = SessionDB(path)
    writer.create_session("s1", "test", session_key="k1", profile_name="offline")
    writer.close()
    before = _file_digest(path)
    reader = SessionDB(path, read_only=True)
    return path, before, reader


def _legacy_lineage_fixture(tmp_path: Path):
    try:
        from hermes_state import SessionDB
    except ModuleNotFoundError as exc:
        pytest.skip(f"legacy SessionDB unavailable: {exc.name}")
    path = tmp_path / "lineage-state.db"
    writer = SessionDB(path)
    writer.create_session("parent", "test", session_key="parent-key", profile_name="offline")
    writer.create_session(
        "child", "test", session_key="child-key", profile_name="offline",
        parent_session_id="parent",
    )
    writer.close()
    before = _file_digest(path)
    reader = SessionDB(path, read_only=True)
    return path, before, reader


def _legacy_multi_fixture(tmp_path: Path):
    try:
        from hermes_state import SessionDB
    except ModuleNotFoundError as exc:
        pytest.skip(f"legacy SessionDB unavailable: {exc.name}")
    path = tmp_path / "multi-state.db"
    writer = SessionDB(path)
    for index in ("a", "b", "c"):
        writer.create_session(
            f"session-{index}", f"source-{index}",
            session_key=f"key-{index}", profile_name=f"profile-{index}",
        )
    writer.close()
    before = _file_digest(path)
    reader = SessionDB(path, read_only=True)
    return path, before, reader


def test_projection_is_detached_and_preserves_adapter_metadata():
    row = {"id": "s1", "source": "telegram", "session_key": "k1", "profile_name": "p"}
    core, adapter = project_detached(row)
    assert core.session_id.value == "s1"
    assert core.key.value == "k1"
    assert adapter == {"profile_name": "p"}
    adapter["profile_name"] = "changed"
    assert row["profile_name"] == "p"
    assert not hasattr(core, "db")


@pytest.mark.parametrize("scenario", [f"SP{i:02d}" for i in range(1, 21)])
def test_sp_scenario_uses_real_legacy_or_is_explicitly_unverified(tmp_path, scenario):
    """Every scenario is paired only when the real legacy reader is available."""
    path, before, reader = _legacy_db_or_skip(tmp_path)
    try:
        legacy = reader.get_session("s1")
        assert legacy is not None
        projected, adapter = project_detached(legacy)
        assert projected.session_id.value == legacy["id"]
        assert isinstance(adapter, dict)
        assert _file_digest(path) == before
    finally:
        reader.close()


def test_projection_rejects_missing_or_malformed_fields():
    with pytest.raises(ValueError, match="missing_required_identity"):
        project_detached({"source": "test"})
    with pytest.raises(ValueError, match="malformed_lifecycle"):
        project_detached({"id": "s1", "ended_at": "impossible"})


def test_repeated_projection_is_deterministic_and_source_unchanged():
    row = {"id": "s1", "source": "test", "profile_name": "p", "unknown": {"x": 1}}
    snapshot = deepcopy(row)
    first = project_detached(row)
    second = project_detached(row)
    assert first == second
    first[1]["unknown"]["x"] = 2
    assert row == snapshot


def test_real_legacy_no_write_proof_is_executable_when_dependencies_exist(tmp_path):
    path, before, reader = _legacy_db_or_skip(tmp_path)
    try:
        row = reader.get_session("s1")
        assert row is not None
        project_detached(row)
        with sqlite3.connect(path) as conn:
            assert conn.execute("PRAGMA data_version").fetchone()[0] >= 1
        assert _file_digest(path) == before
    finally:
        reader.close()


def test_sp2_parent_lineage_uses_authoritative_legacy_fixture(tmp_path):
    path, before, reader = _legacy_lineage_fixture(tmp_path)
    try:
        parent = reader.get_session("parent")
        child = reader.get_session("child")
        assert parent is not None and child is not None
        assert child["parent_session_id"] == parent["id"]
        projected, adapter = project_detached(child)
        assert projected.session_id.value == "child"
        assert projected.parent_session_id is not None
        assert projected.parent_session_id.value == parent["id"]
        assert projected.parent_session_id.value != projected.session_id.value
        assert adapter is not child
        adapter["profile_name"] = "mutated"
        assert child["profile_name"] == "offline"
        assert _file_digest(path) == before
    finally:
        reader.close()


def test_sp20_multiple_authoritative_sessions_are_isolated(tmp_path):
    path, before, reader = _legacy_multi_fixture(tmp_path)
    try:
        rows = [reader.get_session(f"session-{index}") for index in ("a", "b", "c")]
        assert all(row is not None for row in rows)
        projections = [project_detached(row) for row in rows]
        identities = [core.session_id.value for core, _ in projections]
        keys = [core.key.value for core, _ in projections]
        assert identities == ["session-a", "session-b", "session-c"]
        assert keys == ["key-a", "key-b", "key-c"]
        assert len(set(identities)) == len(identities)
        assert len(set(keys)) == len(keys)
        assert [adapter["profile_name"] for _, adapter in projections] == [
            "profile-a", "profile-b", "profile-c"
        ]
        projections[0][1]["profile_name"] = "changed"
        assert projections[1][1]["profile_name"] == "profile-b"
        assert projections[2][1]["profile_name"] == "profile-c"
        repeat, _ = project_detached(reader.get_session("session-a"))
        assert repeat == projections[0][0]
        assert _file_digest(path) == before
    finally:
        reader.close()


def test_sp7_ended_session_projects_closed_without_writes(tmp_path):
    from hermes_state import SessionDB

    path = tmp_path / "terminal-state.db"
    writer = SessionDB(path)
    try:
        writer.create_session("parent", "test", profile_name="offline")
        writer.create_session(
            "child", "test", session_key="child-key", profile_name="offline",
            parent_session_id="parent",
        )
        active = writer.get_session("child")
        assert active["ended_at"] is None and active["end_reason"] is None
        assert project_detached(active)[0].status is SessionStatus.ACTIVE
        writer.end_session("child", "session_reset")
        ended = writer.get_session("child")
        assert isinstance(ended["ended_at"], (int, float))
        assert ended["ended_at"] >= active["started_at"]
        assert ended["end_reason"] == "session_reset"
    finally:
        writer.close()

    before = _file_digest(path)
    reader = SessionDB(path, read_only=True)
    try:
        row = reader.get_session("child")
        assert row == ended
        source = deepcopy(row)
        core, adapter = project_detached(row)
        assert core.status is SessionStatus.CLOSED
        assert core.session_id.value == row["id"] == active["id"]
        assert core.key.value == row["session_key"] == active["session_key"]
        assert core.parent_session_id.value == row["parent_session_id"] == "parent"
        assert core.parent_session_id.value != core.session_id.value
        assert adapter["ended_at"] == row["ended_at"]
        assert adapter["end_reason"] == row["end_reason"]
        assert adapter["profile_name"] == row["profile_name"]
        assert project_detached(reader.get_session("child")) == (core, adapter)
        adapter["end_reason"] = "detached-only"
        adapter["profile_name"] = "detached-only"
        core.metadata["source"] = "detached-only"
        assert row == source == reader.get_session("child")
        assert reader.get_session("parent")["ended_at"] is None
        assert _file_digest(path) == before
    finally:
        reader.close()
    assert _file_digest(path) == before


def test_sp8_expiry_finalized_flag_does_not_establish_expired_or_closed(tmp_path):
    """Boundary evidence only: the marker API does not execute expiry policy."""
    from hermes_state import SessionDB

    path = tmp_path / "expiry-marker-state.db"
    writer = SessionDB(path)
    try:
        writer.create_session("marked", "test", profile_name="offline")
        writer.set_expiry_finalized("marked")
    finally:
        writer.close()

    before = _file_digest(path)
    reader = SessionDB(path, read_only=True)
    try:
        row = reader.get_session("marked")
        source = deepcopy(row)
        assert row["expiry_finalized"] == 1
        assert row["ended_at"] is None and row["end_reason"] is None
        core, adapter = project_detached(row)
        assert core.status is SessionStatus.ACTIVE
        assert adapter["expiry_finalized"] == row["expiry_finalized"]
        assert project_detached(reader.get_session("marked")) == (core, adapter)
        adapter["expiry_finalized"] = 0
        assert row == source == reader.get_session("marked")
        assert _file_digest(path) == before
    finally:
        reader.close()
    assert _file_digest(path) == before


def test_sp9_real_profile_source_origin_preserved(tmp_path):
    from hermes_state import SessionDB

    path = tmp_path / "origin-state.db"
    origin = json.dumps({"platform": "local", "chat_id": "offline-chat"})
    writer = SessionDB(path)
    try:
        writer.create_session("parent", "local", profile_name="offline")
        writer.create_session(
            "child", "local", session_key="offline-key", parent_session_id="parent",
            profile_name="offline", origin_json=origin, chat_id="offline-chat",
            chat_type="dm", user_id="offline-user", display_name="Offline origin",
        )
    finally:
        writer.close()
    before = _file_digest(path)
    reader = SessionDB(path, read_only=True)
    try:
        row = reader.get_session("child")
        snapshot = deepcopy(row)
        assert row["source"] == "local"
        assert row["profile_name"] == "offline"
        assert row["origin_json"] == origin
        core, adapter = project_detached(row)
        assert core.metadata == {"source": row["source"]}
        assert core.session_id.value == row["id"] == "child"
        assert core.key.value == row["session_key"] == "offline-key"
        assert core.parent_session_id.value == row["parent_session_id"] == "parent"
        assert row["ended_at"] is None and core.status is SessionStatus.ACTIVE
        for field in ("profile_name", "origin_json", "chat_id", "chat_type", "user_id", "display_name"):
            assert adapter[field] == row[field]
            assert type(adapter[field]) is type(row[field])
        assert "profile_name" not in core.metadata and "origin_json" not in core.metadata
        assert adapter is not row
        assert project_detached(reader.get_session("child")) == (core, adapter)
        core.metadata["source"] = "detached-source"
        adapter["profile_name"] = "detached-profile"
        adapter["origin_json"] = "null"
        assert row == snapshot == reader.get_session("child")
        assert _file_digest(path) == before
    finally:
        reader.close()
    assert _file_digest(path) == before


def test_sp12_real_adapter_fields_preserve_types_and_session_isolation(tmp_path):
    """Current repository fields outside core ownership, not future-schema proof."""
    from hermes_state import SessionDB

    path = tmp_path / "adapter-state.db"
    writer = SessionDB(path)
    try:
        for name in ("a", "b"):
            writer.create_session(
                name, "local", session_key=f"key-{name}", profile_name=f"profile-{name}",
                model=f"offline-model-{name}", model_config={"model": f"offline-model-{name}"},
                display_name=f"Session {name}", cwd=str(tmp_path / name),
            )
    finally:
        writer.close()
    before = _file_digest(path)
    reader = SessionDB(path, read_only=True)
    try:
        rows = [reader.get_session(name) for name in ("a", "b")]
        snapshots = deepcopy(rows)
        projections = [project_detached(row) for row in rows]
        for name, row, (core, adapter) in zip(("a", "b"), rows, projections):
            assert row["model"] == f"offline-model-{name}"
            assert json.loads(row["model_config"]) == {"model": row["model"]}
            assert row["display_name"] == f"Session {name}"
            assert row["cwd"] == str(tmp_path / name)
            assert type(row["started_at"]) is float
            assert type(row["expiry_finalized"]) is int
            assert type(row["model_config"]) is str
            assert row["end_reason"] is None
            expected_fields = row.keys() - {"id", "session_key", "parent_session_id", "source"}
            assert adapter.keys() == expected_fields
            for field in expected_fields:
                assert adapter[field] == row[field]
                assert type(adapter[field]) is type(row[field])
            # SQLite row values here are scalars, including serialized JSON text.
            assert all(value is None or type(value) in (str, int, float, bytes) for value in row.values())
            assert core.session_id.value == row["id"] == name
            assert core.key.value == row["session_key"]
            assert core.status is SessionStatus.ACTIVE
            assert core.parent_session_id is None
            assert adapter is not row
            assert project_detached(reader.get_session(name)) == (core, adapter)
        pristine = deepcopy(projections)
        projections[0][1]["model_config"] = "null"
        projections[0][1]["display_name"] = "detached"
        projections[0][0].metadata["source"] = "detached"
        assert projections[1] == pristine[1]
        assert rows == snapshots
        for index, name in enumerate(("a", "b")):
            assert reader.get_session(name) == snapshots[index]
            assert project_detached(reader.get_session(name)) == pristine[index]
        assert _file_digest(path) == before
    finally:
        reader.close()
    assert _file_digest(path) == before
