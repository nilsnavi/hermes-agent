"""PostgreSQL authority schema migrations.

Canonical DDL for the platform control-plane store. The schema enforces:

* tenant_id on every table (rock-solid tenant isolation at the DB boundary);
* user-scope columns where a record is user-owned;
* FK RESTRICT for audit-critical referential integrity;
* an append-only audit table guarded by a trigger that rejects UPDATE/DELETE;
* optimistic-concurrency ``version`` columns on every mutable row.

Migrations are reversible pairs (up/down). The engine executes them; this
module is data-only and stdlib-only.
"""

from __future__ import annotations

from .migrations import Migration

_UP_0001: tuple[str, ...] = (
    """
    CREATE TABLE tenants (
        tenant_id      TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        created_at     BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE agents (
        agent_id          TEXT NOT NULL,
        version           INTEGER NOT NULL,
        tenant_id         TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
        name              TEXT NOT NULL,
        role              TEXT NOT NULL,
        implementation_id TEXT NOT NULL,
        capabilities      JSONB NOT NULL DEFAULT '[]',
        trust_score       DOUBLE PRECISION NOT NULL DEFAULT 0,
        permissions       JSONB NOT NULL DEFAULT '{}',
        status            TEXT NOT NULL DEFAULT 'registered',
        updated_at        BIGINT NOT NULL,
        version_row       INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (agent_id, version),
        UNIQUE (agent_id, tenant_id)
    )
    """,
    """
    CREATE TABLE tasks (
        task_id      TEXT PRIMARY KEY,
        tenant_id    TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
        user_id      TEXT NOT NULL,
        goal         TEXT NOT NULL,
        status       TEXT NOT NULL,
        version      INTEGER NOT NULL DEFAULT 0,
        context_json TEXT NOT NULL DEFAULT '{}',
        created_at   BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE agent_runs (
        run_id       TEXT PRIMARY KEY,
        task_id      TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
        agent_id     TEXT NOT NULL,
        tenant_id    TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE RESTRICT,
        user_id      TEXT NOT NULL,
        status       TEXT NOT NULL,
        result_json  TEXT NOT NULL DEFAULT '{}',
        duration_ms  INTEGER,
        success      BOOLEAN,
        created_at   BIGINT NOT NULL
    )
    """,
    """
    CREATE TABLE audit_events (
        entry_id      TEXT PRIMARY KEY,
        tenant_id     TEXT NOT NULL,
        actor         TEXT NOT NULL,
        action        TEXT NOT NULL,
        occurred_at   BIGINT NOT NULL,
        payload_digest TEXT NOT NULL DEFAULT '',
        sequence      INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX idx_tasks_tenant ON tasks(tenant_id)
    """,
    """
    CREATE INDEX idx_agent_runs_tenant ON agent_runs(tenant_id)
    """,
)

_DOWN_0001: tuple[str, ...] = (
    "DROP TABLE IF EXISTS audit_events",
    "DROP TABLE IF EXISTS agent_runs",
    "DROP TABLE IF EXISTS tasks",
    "DROP TABLE IF EXISTS agents",
    "DROP TABLE IF EXISTS tenants",
)

_UP_0002: tuple[str, ...] = (
    """
    CREATE FUNCTION audit_events_no_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER audit_events_no_update
        BEFORE UPDATE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_no_mutation()
    """,
    """
    CREATE TRIGGER audit_events_no_delete
        BEFORE DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_no_mutation()
    """,
)

_DOWN_0002: tuple[str, ...] = (
    "DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events",
    "DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events",
    "DROP FUNCTION IF EXISTS audit_events_no_mutation()",
)

# The canonical schema, applied by the migration engine in order.
SCHEMA_MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "platform_authority_schema", _UP_0001, _DOWN_0001),
    Migration(2, "audit_append_only_guard", _UP_0002, _DOWN_0002),
)