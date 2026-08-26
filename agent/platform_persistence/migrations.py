"""Reversible platform migrations.

The migration engine is authoritative over the platform schema. Every migration
has an ``up`` and a matching ``down`` (down may raise NotImplementedError only
for flagged irreversible migrations, which the registry refuses by default).
A migration is applied only through the engine, in strict order, and never
rewrites a schema backwards. The engine is pure and stdlib-only: it does not
open connections; an adapter supplies the dialect executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from .exceptions import MigrationConflict, MigrationNotReversible


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    up: tuple[str, ...]
    down: tuple[str, ...]
    irreversible: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version < 1
        ):
            raise MigrationConflict("migration version must be a positive integer")
        if not isinstance(self.name, str) or not self.name.strip():
            raise MigrationConflict("migration name must be a non-empty string")
        if not isinstance(self.up, tuple) or not self.up:
            raise MigrationConflict("migration up must be a non-empty tuple of statements")
        if not isinstance(self.down, tuple):
            raise MigrationConflict("migration down must be a tuple of statements")
        if not self.down and not self.irreversible:
            raise MigrationNotReversible(
                f"migration {self.version} ({self.name}) is missing a down migration"
            )

    @property
    def key(self) -> tuple[int, str]:
        return (self.version, self.name)


class SchemaExecutor(Protocol):
    """Dialect-aware executor of SQL statements (provided by an adapter)."""

    def execute(self, statements: Iterable[str]) -> None: ...


def _require_migration(value: object) -> Migration:
    if type(value) is not Migration:
        raise MigrationConflict("expected an exact Migration value")
    return value


class MigrationRegistry:
    """Ordered, deduplicated migration set enforcing reversibility."""

    def __init__(self) -> None:
        self.__migrations: list[Migration] = []
        self.__versions: set[int] = set()
        self.__names: set[str] = set()

    def add(self, migration: Migration) -> None:
        migration = _require_migration(migration)
        if migration.version in self.__versions:
            raise MigrationConflict(
                f"duplicate migration version {migration.version}"
            )
        if migration.name in self.__names:
            raise MigrationConflict(f"duplicate migration name {migration.name!r}")
        self.__versions.add(migration.version)
        self.__names.add(migration.name)
        self.__migrations.append(migration)
        self.__migrations.sort(key=lambda m: m.version)

    def add_all(self, migrations: Iterable[Migration]) -> None:
        for migration in migrations:
            self.add(migration)

    def latest_version(self) -> int:
        if not self.__migrations:
            return 0
        return self.__migrations[-1].version

    def plan(self, target_version: int) -> tuple[Migration, ...]:
        """Return migrations needed to go from 0 to target_version (up only)."""
        if (
            isinstance(target_version, bool)
            or not isinstance(target_version, int)
            or target_version < 0
            or target_version > self.latest_version()
        ):
            raise MigrationConflict(
                f"target_version must be an int in [0, {self.latest_version()}]"
            )
        return tuple(
            migration
            for migration in self.__migrations
            if migration.version <= target_version
        )

    def rollback_plan(self, from_version: int, to_version: int) -> tuple[Migration, ...]:
        """Return migrations to roll back (down), from high to low, to_version exclusive."""
        if (
            isinstance(from_version, bool)
            or not isinstance(from_version, int)
            or isinstance(to_version, bool)
            or not isinstance(to_version, int)
            or from_version < 0
            or to_version < 0
            or from_version <= to_version
        ):
            raise MigrationConflict(
                "rollback requires from_version > to_version >= 0"
            )
        reversed_migrations = list(reversed(self.__migrations))
        selected = [
            migration
            for migration in reversed_migrations
            if to_version < migration.version <= from_version
        ]
        for migration in selected:
            if not migration.down:
                raise MigrationNotReversible(
                    f"migration {migration.version} ({migration.name}) cannot be rolled back"
                )
        return tuple(selected)

    def snapshot(self) -> tuple[Migration, ...]:
        return tuple(self.__migrations)


def migrate_up(
    registry: MigrationRegistry,
    target_version: int,
    executor: SchemaExecutor,
) -> int:
    """Apply all up-migrations up to and including target_version."""
    plan = registry.plan(target_version)
    for migration in plan:
        executor.execute(migration.up)
    return target_version


def migrate_down(
    registry: MigrationRegistry,
    from_version: int,
    to_version: int,
    executor: SchemaExecutor,
) -> int:
    """Roll back to_version exclusive, executing down-migrations high-to-low."""
    rollback = registry.rollback_plan(from_version, to_version)
    for migration in rollback:
        executor.execute(migration.down)
    return to_version