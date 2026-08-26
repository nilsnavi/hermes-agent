"""Exceptions raised by platform persistence contracts."""

from __future__ import annotations


class PlatformPersistenceError(ValueError):
    """Base error for invalid platform persistence contracts."""


class MigrationConflict(PlatformPersistenceError):
    """Raised when migration ordering or reversibility is violated."""


class MigrationNotReversible(PlatformPersistenceError):
    """Raised when a migration is missing its down migration."""


class TenantIsolationViolation(PlatformPersistenceError):
    """Raised when a record is accessed beyond its tenant/user boundary."""


class AuditMutationForbidden(PlatformPersistenceError):
    """Raised when an append-only audit record is mutated."""