"""Runtime V2 store factory + schema gate (Sprint 1.0.6 §23-27).

Two PHASES:
- ``schema_check(db)`` — ZERO writes: reports required/existing tables,
  planned DDL, legacy-changed: NO.
- ``schema_apply(db)`` — EXPLICIT, additive-only: CREATE TABLE IF NOT
  EXISTS agent_v2_* (idempotent, transaction-safe). Never ALTERs legacy
  tables; never runs automatically at import.

Store creation honors the flags: persistence disabled → None (no schema,
no file); canary → temp SQLite by default; production state.db ONLY when
``allow_production=True`` AND schema_check passed AND explicitly requested.
"""

import os
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional

from agent.persistence import SQLiteExecutionStore
from agent.persistence.schema import ALL_TABLES, ensure_execution_schema

from .flags import FeatureFlags

_PLANNED_DDL = [
    "CREATE TABLE IF NOT EXISTS agent_v2_runs (...)",
    "CREATE TABLE IF NOT EXISTS agent_v2_plans (...)",
    "CREATE TABLE IF NOT EXISTS agent_v2_steps (...)",
    "CREATE TABLE IF NOT EXISTS agent_v2_approvals (...)",
    "CREATE TABLE IF NOT EXISTS agent_v2_events (...)",
    "CREATE TABLE IF NOT EXISTS agent_v2_meta (...)",
    "CREATE INDEX IF NOT EXISTS idx_agent_v2_* (additive)",
]


def _connect_readonly(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def schema_check(path: str) -> Dict[str, Any]:
    """Read-only report. Opens the DB with mode=ro — ZERO writes."""
    if not os.path.exists(path):
        return {
            "db": os.path.basename(path),
            "required_tables": list(ALL_TABLES),
            "existing_tables": [],
            "v2_tables_present": [],
            "v2_tables_missing": list(ALL_TABLES),
            "planned_ddl": _PLANNED_DDL,
            "legacy_objects_changed": "NO",
            "legacy_tables": [],
            "writes": 0,
        }
    conn = _connect_readonly(path)
    try:
        existing = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        v2_existing = [t for t in ALL_TABLES if t in existing]
        legacy = {t for t in existing if not t.startswith("agent_v2_")}
        return {
            "db": os.path.basename(path),
            "required_tables": list(ALL_TABLES),
            "existing_tables": sorted(existing),
            "v2_tables_present": v2_existing,
            "v2_tables_missing": [t for t in ALL_TABLES if t not in existing],
            "planned_ddl": _PLANNED_DDL,
            # Zero writes by construction: check is read-only; apply runs
            # CREATE TABLE IF NOT EXISTS on agent_v2_* names only.
            "legacy_objects_changed": "NO",
            "legacy_tables": sorted(legacy),
            "writes": 0,
        }
    finally:
        conn.close()


def schema_apply(path: str) -> Dict[str, Any]:
    """EXPLICIT additive activation. CREATE TABLE IF NOT EXISTS only.

    Runs the same idempotent initializer the store itself uses; legacy
    tables are untouched by construction (no ALTER/DROP ever).
    """
    before = schema_check(path)
    conn = sqlite3.connect(path)
    try:
        ensure_execution_schema(conn)
        conn.execute("PRAGMA integrity_check")
    finally:
        conn.close()
    after = schema_check(path)
    return {
        "applied": True,
        "tables_before": before["v2_tables_present"],
        "tables_after": after["v2_tables_present"],
        "additive_only": set(after["existing_tables"]) >= set(before["existing_tables"]),
        "legacy_objects_changed": "NO",
    }


class RuntimeV2StoreFactory:
    def __init__(self, flags: Optional[FeatureFlags] = None) -> None:
        self._flags = flags or FeatureFlags()

    def create_store(
        self,
        db_path: Optional[str] = None,
        allow_production: bool = False,
    ) -> Optional[SQLiteExecutionStore]:
        """Store for V2 canary runs.

        - flags disabled / persistence disabled → None (no schema, no file);
        - explicit ``db_path`` + allow_production → that path (caller must
          have run schema_apply first);
        - otherwise → a throwaway temp SQLite file (default canary behavior).
        """
        if not self._flags.enabled or not self._flags.persistence:
            return None
        if db_path is not None and allow_production:
            return SQLiteExecutionStore(db_path)
        tmp = os.path.join(tempfile.mkdtemp(prefix="v2-canary-"), "canary.db")
        return SQLiteExecutionStore(tmp)

    def schema_ready(self, db_path: str) -> bool:
        if not self._flags.enabled or not self._flags.persistence:
            return False
        try:
            return not schema_check(db_path)["v2_tables_missing"]
        except Exception:
            return False
