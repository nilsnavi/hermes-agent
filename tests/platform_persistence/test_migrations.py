"""Reversible migration engine tests."""

import pytest

from agent.platform_persistence.exceptions import MigrationConflict, MigrationNotReversible
from agent.platform_persistence.migrations import (
    Migration,
    MigrationRegistry,
    migrate_down,
    migrate_up,
)
from agent.platform_persistence.pg_schema import SCHEMA_MIGRATIONS


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, statements) -> None:
        for statement in statements:
            stripped = statement.strip()
            if stripped:
                self.calls.append(stripped)


def _migration(
    version: int,
    name: str,
    up=("CREATE TABLE x",),
    down=("DROP TABLE x",),
    irreversible: bool = False,
) -> Migration:
    return Migration(
        version, name, tuple(up), tuple(down), irreversible=irreversible
    )


def test_migration_requires_down_unless_irreversible():
    with pytest.raises(MigrationNotReversible):
        Migration(1, "a", ("CREATE",), ())


def test_migration_irreversible_flag_allows_missing_down():
    m = Migration(1, "a", ("CREATE",), (), irreversible=True)
    assert m.irreversible


def test_registry_orders_by_version():
    registry = MigrationRegistry()
    registry.add(_migration(2, "b"))
    registry.add(_migration(1, "a"))
    assert [m.version for m in registry.snapshot()] == [1, 2]


def test_registry_rejects_duplicate_version():
    registry = MigrationRegistry()
    registry.add(_migration(1, "a"))
    with pytest.raises(MigrationConflict):
        registry.add(_migration(1, "c"))


def test_registry_rejects_duplicate_name():
    registry = MigrationRegistry()
    registry.add(_migration(1, "a"))
    with pytest.raises(MigrationConflict):
        registry.add(_migration(2, "a"))


def test_migrate_up_executes_all_up_to_target():
    registry = MigrationRegistry()
    registry.add_all([_migration(1, "a"), _migration(2, "b"), _migration(3, "c")])
    executor = _RecordingExecutor()
    assert migrate_up(registry, 2, executor) == 2
    assert executor.calls == ["CREATE TABLE x", "CREATE TABLE x"]


def test_migrate_down_is_reversible_order():
    registry = MigrationRegistry()
    registry.add_all([_migration(1, "a"), _migration(2, "b"), _migration(3, "c")])
    executor = _RecordingExecutor()
    assert migrate_down(registry, 3, 1, executor) == 1
    # Down of 3, then down of 2 (down of 1 is NOT executed, exclusive target).
    assert executor.calls == ["DROP TABLE x", "DROP TABLE x"]


def test_rollback_to_zero_denies_for_irreversible():
    registry = MigrationRegistry()
    registry.add(_migration(1, "a", up=("CREATE",), down=(), irreversible=True))
    with pytest.raises(MigrationNotReversible):
        migrate_down(registry, 1, 0, _RecordingExecutor())


def test_canonical_schema_is_reversible_and_ordered():
    assert [m.version for m in SCHEMA_MIGRATIONS] == [1, 2]
    for migration in SCHEMA_MIGRATIONS:
        assert migration.down


def test_plan_rejects_target_beyond_latest():
    registry = MigrationRegistry()
    registry.add(_migration(1, "a"))
    with pytest.raises(MigrationConflict):
        registry.plan(2)


def test_latest_version_zero_when_empty():
    assert MigrationRegistry().latest_version() == 0


def test_canonical_schema_enforces_tenant_isolation_at_db_boundary():
    # Every authority table must carry a tenant column so isolation holds at the
    # storage boundary, not only in the application model.
    from agent.platform_persistence.pg_schema import SCHEMA_MIGRATIONS

    migration1 = SCHEMA_MIGRATIONS[0]
    for table in ("tenants", "agents", "tasks", "agent_runs", "audit_events"):
        create_stmt = next(
            stmt for stmt in migration1.up if f"CREATE TABLE {table}" in stmt
        )
        assert "tenant_id" in create_stmt, f"{table} missing tenant_id"


def test_canonical_schema_guards_audit_append_only():
    from agent.platform_persistence.pg_schema import SCHEMA_MIGRATIONS

    migration2 = SCHEMA_MIGRATIONS[1]
    joined = "\n".join(migration2.up)
    assert "no_update" in joined
    assert "no_delete" in joined
    assert "RAISE EXCEPTION" in joined
    # Down restores the mutable state.
    assert "DROP TRIGGER" in "\n".join(migration2.down)