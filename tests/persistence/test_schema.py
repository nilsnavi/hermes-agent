"""Schema / migration tests (Sprint 1.0.3 §32)."""

import sqlite3

import pytest

from agent.persistence import schema


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _tables(conn):
    return {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}


def test_empty_db_gets_full_schema(tmp_path):
    conn = _connect(str(tmp_path / "empty.db"))
    schema.ensure_execution_schema(conn)
    assert set(schema.ALL_TABLES) <= _tables(conn)
    version = conn.execute(
        f"SELECT value FROM {schema.META} WHERE key='schema_version'"
    ).fetchone()["value"]
    assert version == schema.SCHEMA_VERSION
    conn.close()


def test_schema_is_idempotent(tmp_path):
    conn = _connect(str(tmp_path / "idem.db"))
    schema.ensure_execution_schema(conn)
    # Second run: no error, no change.
    schema.ensure_execution_schema(conn)
    assert set(schema.ALL_TABLES) <= _tables(conn)
    conn.close()


def test_legacy_like_tables_untouched(tmp_path):
    conn = _connect(str(tmp_path / "legacy.db"))
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY, title TEXT)"
    )
    conn.execute("INSERT INTO sessions (title) VALUES ('legacy row')")
    conn.commit()
    schema.ensure_execution_schema(conn)
    # Legacy table + its data survive; new tables coexist.
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    assert "sessions" in _tables(conn)
    assert set(schema.ALL_TABLES) <= _tables(conn)
    conn.close()


def test_partial_schema_repairs_additively(tmp_path):
    """A half-created v2 schema (e.g. crash mid-migration) must be completed
    without destroying existing v2 data."""
    conn = _connect(str(tmp_path / "partial.db"))
    conn.execute(
        f"CREATE TABLE {schema.RUNS} (id TEXT PRIMARY KEY, task_type TEXT NOT NULL, "
        "status TEXT NOT NULL, model_profile TEXT NOT NULL, created_at TEXT NOT NULL, "
        "started_at TEXT, completed_at TEXT, error TEXT, result_json TEXT, "
        "context_json TEXT, version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        f"INSERT INTO {schema.RUNS} (id, task_type, status, model_profile, "
        "created_at, updated_at) VALUES ('r1', 't', 'created', 'BALANCED', '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    schema.ensure_execution_schema(conn)
    # Existing v2 data untouched, missing tables added.
    assert conn.execute(
        f"SELECT COUNT(*) FROM {schema.RUNS}"
    ).fetchone()[0] == 1
    assert set(schema.ALL_TABLES) <= _tables(conn)
    conn.close()


def test_foreign_keys_enforced(tmp_path):
    conn = _connect(str(tmp_path / "fk.db"))
    schema.ensure_execution_schema(conn)
    # plan without a run → FK violation
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            f"INSERT INTO {schema.PLANS} (id, run_id, goal, status, updated_at) "
            "VALUES ('p1', 'missing-run', 'g', 'created', '2026-01-01')"
        )
    conn.close()
