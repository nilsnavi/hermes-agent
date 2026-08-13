"""Additive operations-layer schema migration (Sprint 1.0.6.3 §59-60).

The approvals table gains three nullable decision-metadata columns
(``decided_by`` / ``decision_source`` / ``decision_reason_code``).
Migration is:

- ADDITIVE only (ALTER TABLE ADD COLUMN; legacy tables untouched);
- idempotent (column-existence guard per column);
- versioned in ``agent_v2_meta`` (``operations_schema_version``).

Fresh databases already carry the columns via ``schema.py`` — this
module is a no-op for them. The store itself is tolerant of the old
schema (dynamic column introspection), so both paths stay safe
regardless of migration ordering.
"""

import os
import sqlite3
from typing import List

from agent.persistence.schema import APPROVALS, META

OPERATIONS_SCHEMA_VERSION = "1"

_NEW_COLUMNS = (
    ("decided_by", "TEXT"),
    ("decision_source", "TEXT"),
    ("decision_reason_code", "TEXT"),
)


def _existing_columns(conn: sqlite3.Connection) -> set:
    return {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({APPROVALS})").fetchall()
    }


def schema_check(db_path: str) -> dict:
    """Read-only report of the operations schema state (ZERO writes)."""
    if not os.path.exists(db_path):
        return {"db": db_path, "operations_schema_version": None,
                "missing_columns": [c for c, _ in _NEW_COLUMNS]}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cols = _existing_columns(conn)
        version = conn.execute(
            f"SELECT value FROM {META} WHERE key='operations_schema_version'"
        ).fetchone()
        return {
            "db": db_path,
            "operations_schema_version": version[0] if version else None,
            "missing_columns": [c for c, _ in _NEW_COLUMNS if c not in cols],
        }
    finally:
        conn.close()


def ensure_operations_schema(db_path: str) -> dict:
    """Idempotent additive migration. Runs its own transaction."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cols = _existing_columns(conn)
        added: List[str] = []
        for name, ddl_type in _NEW_COLUMNS:
            if name not in cols:
                conn.execute(
                    f"ALTER TABLE {APPROVALS} ADD COLUMN {name} {ddl_type}"
                )
                added.append(name)
        conn.execute(
            f"INSERT OR REPLACE INTO {META}(key, value) "
            f"VALUES ('operations_schema_version', ?)",
            (OPERATIONS_SCHEMA_VERSION,),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "applied": True,
        "columns_added": added,
        "operations_schema_version": OPERATIONS_SCHEMA_VERSION,
        "additive_only": True,
    }
