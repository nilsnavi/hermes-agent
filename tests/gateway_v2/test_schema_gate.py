"""Schema gate tests (Sprint 1.0.6 §25-27/59, MUST-HAVE 17-19)."""

import os
import sqlite3

from agent.gateway_v2.store_factory import schema_apply, schema_check
from agent.persistence.schema import ALL_TABLES


def _make_legacy_db(path):
    """Create a DB with legacy-style tables (sessions/messages)."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, data TEXT)")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
    conn.execute("INSERT INTO sessions VALUES ('s1', 'hello')")
    conn.commit()
    conn.close()


def test_schema_check_zero_writes(tmp_path):
    """MUST-HAVE 17 — schema-check opens read-only; no file is created."""
    path = str(tmp_path / "check.db")
    result = schema_check(path)
    assert result["writes"] == 0
    assert result["v2_tables_missing"] == list(ALL_TABLES)
    assert result["legacy_objects_changed"] == "NO"
    assert not os.path.exists(path)  # read-only → no DB file created


def test_schema_check_on_existing_db_is_read_only(tmp_path):
    path = str(tmp_path / "existing.db")
    _make_legacy_db(path)
    before = os.path.getmtime(path)
    result = schema_check(path)
    assert result["writes"] == 0
    assert result["legacy_tables"] == ["messages", "sessions"]
    assert result["v2_tables_present"] == []
    assert os.path.getmtime(path) == before  # untouched


def test_schema_apply_additive_only(tmp_path):
    """MUST-HAVE 18 — apply adds ONLY agent_v2_* objects."""
    path = str(tmp_path / "apply.db")
    _make_legacy_db(path)
    result = schema_apply(path)
    assert result["additive_only"] is True
    assert len(result["tables_after"]) == len(ALL_TABLES)

    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    # sqlite_sequence is an internal sqlite bookkeeping table (AUTOINCREMENT)
    legacy = {t for t in tables
              if not t.startswith("agent_v2_") and t != "sqlite_sequence"}
    assert legacy == {"sessions", "messages"}  # legacy UNCHANGED
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    # legacy row untouched (MUST-HAVE 19)
    assert conn.execute("SELECT data FROM sessions WHERE id='s1'").fetchone()[0] == "hello"
    conn.close()


def test_schema_apply_idempotent(tmp_path):
    path = str(tmp_path / "idem.db")
    first = schema_apply(path)
    second = schema_apply(path)  # repeat → no error, no change
    assert first["additive_only"] is True
    assert second["additive_only"] is True
    assert first["tables_after"] == second["tables_after"]


def test_legacy_objects_unchanged_after_apply(tmp_path):
    path = str(tmp_path / "legacy.db")
    _make_legacy_db(path)
    schema_apply(path)
    conn = sqlite3.connect(path)
    fts = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fts%'")]
    triggers = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
    assert fts == []  # no FTS created
    assert triggers == []  # no new triggers
    conn.close()


def test_schema_apply_reports_planned_ddl():
    """Planned DDL is visible BEFORE any mutation (§25)."""
    import tempfile

    path = os.path.join(tempfile.mkdtemp(), "p.db")
    result = schema_check(path)
    assert any("agent_v2_runs" in ddl for ddl in result["planned_ddl"])
    assert not os.path.exists(path)
