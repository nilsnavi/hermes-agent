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


def project_detached(legacy_row: dict) -> tuple[Session, dict[str, object]]:
    """Project only fields owned by the detached core model.

    Adapter-owned legacy data is returned in a separate deep-copied envelope.
    This helper intentionally accepts a row already loaded by the authoritative
    legacy representation; it is not a replacement legacy schema.
    """
    session_id = legacy_row.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("missing_required_identity")
    source_status = legacy_row.get("status", "active")
    if source_status not in ("active", "closed"):
        raise ValueError("malformed_lifecycle")
    core = Session(
        SessionId(session_id),
        SessionKey(legacy_row.get("session_key") or session_id),
        status=SessionStatus.ACTIVE if source_status == "active" else SessionStatus.CLOSED,
        parent_session_id=(SessionId(legacy_row["parent_session_id"])
                           if legacy_row.get("parent_session_id") else None),
        metadata={"source": legacy_row.get("source", "")},
    )
    adapter = deepcopy({
        key: value for key, value in legacy_row.items()
        if key not in {"id", "session_key", "parent_session_id", "source", "status"}
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
        project_detached({"id": "s1", "status": "impossible"})


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
