"""Hermes 2.0 namespaced schema (Sprint 1.0.3).

All tables live under the ``agent_v2_`` prefix inside the existing state.db
(or any SQLite file) — additive-only, idempotent, transaction-safe. Legacy
tables (sessions/messages/FTS) are NEVER touched; the legacy
``schema_version`` is untouched (our own version lives in
``agent_v2_meta``).

Foreign keys use ON DELETE RESTRICT — audit history is preserved; nothing
cascades away silently.
"""

import sqlite3

SCHEMA_VERSION = "1"

RUNS = "agent_v2_runs"
PLANS = "agent_v2_plans"
STEPS = "agent_v2_steps"
APPROVALS = "agent_v2_approvals"
EVENTS = "agent_v2_events"
META = "agent_v2_meta"

ALL_TABLES = (RUNS, PLANS, STEPS, APPROVALS, EVENTS, META)

_SCHEMA_STATEMENTS = [
    # ── runs ────────────────────────────────────────────────────────
    f"""
    CREATE TABLE IF NOT EXISTS {RUNS} (
        id            TEXT PRIMARY KEY,
        task_type     TEXT NOT NULL,
        status        TEXT NOT NULL,
        model_profile TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        started_at    TEXT,
        completed_at  TEXT,
        error         TEXT,
        result_json   TEXT,
        context_json  TEXT,
        version       INTEGER NOT NULL DEFAULT 1,
        updated_at    TEXT NOT NULL
    )
    """,
    # ── plans ───────────────────────────────────────────────────────
    f"""
    CREATE TABLE IF NOT EXISTS {PLANS} (
        id            TEXT PRIMARY KEY,
        run_id        TEXT NOT NULL REFERENCES {RUNS}(id) ON DELETE RESTRICT,
        goal          TEXT NOT NULL,
        status        TEXT NOT NULL,
        created_at    TEXT,
        started_at    TEXT,
        completed_at  TEXT,
        metadata_json TEXT,
        version       INTEGER NOT NULL DEFAULT 1,
        updated_at    TEXT NOT NULL
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_{PLANS}_run ON {PLANS}(run_id)",
    # ── steps ───────────────────────────────────────────────────────
    # Sprint 1.0.6.2 fix: composite PK (plan_id, id) — step ids are
    # per-run ("step-1" repeats in every plan); PK(id) alone let
    # save_step's ON CONFLICT(id) silently OVERWRITE another run's step
    # rows (proven on production by the first canary batch).
    f"""
    CREATE TABLE IF NOT EXISTS {STEPS} (
        id                 TEXT NOT NULL,
        plan_id            TEXT NOT NULL REFERENCES {PLANS}(id) ON DELETE RESTRICT,
        run_id             TEXT NOT NULL,
        sequence           INTEGER NOT NULL,
        name               TEXT NOT NULL,
        description        TEXT NOT NULL DEFAULT '',
        tool               TEXT NOT NULL,
        arguments_json     TEXT,
        requires_approval  INTEGER NOT NULL DEFAULT 0,
        status             TEXT NOT NULL,
        result_json        TEXT,
        error              TEXT,
        created_at         TEXT,
        started_at         TEXT,
        completed_at       TEXT,
        updated_at         TEXT,
        version            INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (plan_id, id)
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_{STEPS}_run ON {STEPS}(run_id)",
    f"CREATE INDEX IF NOT EXISTS idx_{STEPS}_plan ON {STEPS}(plan_id)",
    f"CREATE INDEX IF NOT EXISTS idx_{STEPS}_status ON {STEPS}(status)",
    # ── approvals ────────────────────────────────────────────────────
    f"""
    CREATE TABLE IF NOT EXISTS {APPROVALS} (
        id                   TEXT PRIMARY KEY,
        run_id               TEXT NOT NULL REFERENCES {RUNS}(id) ON DELETE RESTRICT,
        step_id              TEXT NOT NULL,
        reason               TEXT NOT NULL DEFAULT '',
        status               TEXT NOT NULL,
        created_at           TEXT,
        expires_at           TEXT,
        decided_at           TEXT,
        decision_reason      TEXT,
        decided_by           TEXT,
        decision_source      TEXT,
        decision_reason_code TEXT,
        version              INTEGER NOT NULL DEFAULT 1,
        updated_at           TEXT NOT NULL
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_{APPROVALS}_run ON {APPROVALS}(run_id)",
    f"CREATE INDEX IF NOT EXISTS idx_{APPROVALS}_status ON {APPROVALS}(status)",
    # ── event journal (append-only) ─────────────────────────────────
    f"""
    CREATE TABLE IF NOT EXISTS {EVENTS} (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT NOT NULL,
        step_id      TEXT,
        event_type   TEXT NOT NULL,
        timestamp    TEXT NOT NULL,
        payload_json TEXT,
        input_hash   TEXT,
        output_hash  TEXT
    )
    """,
    f"CREATE INDEX IF NOT EXISTS idx_{EVENTS}_run ON {EVENTS}(run_id)",
    f"CREATE INDEX IF NOT EXISTS idx_{EVENTS}_type ON {EVENTS}(event_type)",
    # ── namespaced meta (NOT the legacy schema_version) ─────────────
    f"""
    CREATE TABLE IF NOT EXISTS {META} (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
]


def ensure_execution_schema(conn: sqlite3.Connection) -> None:
    """Idempotent, transaction-safe schema initializer.

    Safe to call on: empty DB, existing v2 DB (no-op), or a legacy DB
    (additive only — legacy tables untouched). Runs in ONE transaction.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.execute(
            f"INSERT OR IGNORE INTO {META}(key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
