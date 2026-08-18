"""Deterministic, test-only fault injection for sandbox mutations."""
from __future__ import annotations

from enum import Enum
from typing import Iterable


class FaultPoint(str, Enum):
    # Planning, policy and preflight
    BEFORE_PLAN = "BEFORE_PLAN"
    AFTER_PLAN = "AFTER_PLAN"
    BEFORE_PREFLIGHT = "BEFORE_PREFLIGHT"
    DURING_PREFLIGHT = "DURING_PREFLIGHT"
    AFTER_PREFLIGHT = "AFTER_PREFLIGHT"
    BEFORE_APPROVAL = "BEFORE_APPROVAL"
    AFTER_APPROVAL = "AFTER_APPROVAL"
    # Snapshot and lock lifecycle
    BEFORE_SNAPSHOT = "BEFORE_SNAPSHOT"
    DURING_SNAPSHOT_CREATE = "DURING_SNAPSHOT_CREATE"
    AFTER_SNAPSHOT_CONTENT = "AFTER_SNAPSHOT_CONTENT"
    AFTER_SNAPSHOT_MANIFEST = "AFTER_SNAPSHOT_MANIFEST"
    AFTER_SNAPSHOT = "AFTER_SNAPSHOT"
    BEFORE_LOCK = "BEFORE_LOCK"
    DURING_LOCK_ACQUIRE = "DURING_LOCK_ACQUIRE"
    AFTER_LOCK = "AFTER_LOCK"
    # Mutation and durable execution receipts
    BEFORE_EXECUTION_RECEIPT = "BEFORE_EXECUTION_RECEIPT"
    AFTER_EXECUTION_RECEIPT = "AFTER_EXECUTION_RECEIPT"
    BEFORE_EXECUTE = "BEFORE_EXECUTE"
    DURING_EXECUTE = "DURING_EXECUTE"
    AFTER_EXECUTE = "AFTER_EXECUTE"
    BEFORE_EXECUTED_RECEIPT = "BEFORE_EXECUTED_RECEIPT"
    AFTER_EXECUTED_RECEIPT = "AFTER_EXECUTED_RECEIPT"
    # Verification and health
    BEFORE_VERIFY = "BEFORE_VERIFY"
    DURING_VERIFY = "DURING_VERIFY"
    AFTER_VERIFY = "AFTER_VERIFY"
    BEFORE_VERIFIED_RECEIPT = "BEFORE_VERIFIED_RECEIPT"
    AFTER_VERIFIED_RECEIPT = "AFTER_VERIFIED_RECEIPT"
    BEFORE_HEALTH = "BEFORE_HEALTH"
    DURING_HEALTH = "DURING_HEALTH"
    AFTER_HEALTH = "AFTER_HEALTH"
    # Commit durability boundary
    BEFORE_COMMIT = "BEFORE_COMMIT"
    DURING_COMMIT_APPEND = "DURING_COMMIT_APPEND"
    AFTER_COMMIT_APPEND = "AFTER_COMMIT_APPEND"
    BEFORE_COMMIT_FSYNC = "BEFORE_COMMIT_FSYNC"
    AFTER_COMMIT_FSYNC = "AFTER_COMMIT_FSYNC"
    AFTER_COMMIT = "AFTER_COMMIT"
    # Rollback lifecycle
    BEFORE_ROLLBACK = "BEFORE_ROLLBACK"
    DURING_ROLLBACK = "DURING_ROLLBACK"
    AFTER_ROLLBACK_RESTORE = "AFTER_ROLLBACK_RESTORE"
    BEFORE_ROLLBACK_VERIFY = "BEFORE_ROLLBACK_VERIFY"
    DURING_ROLLBACK_VERIFY = "DURING_ROLLBACK_VERIFY"
    AFTER_ROLLBACK_VERIFY = "AFTER_ROLLBACK_VERIFY"
    AFTER_ROLLBACK = "AFTER_ROLLBACK"
    # Recovery/reconciliation and journal edge cases
    BEFORE_RECOVERY_SCAN = "BEFORE_RECOVERY_SCAN"
    DURING_RECOVERY_SCAN = "DURING_RECOVERY_SCAN"
    AFTER_RECOVERY_SCAN = "AFTER_RECOVERY_SCAN"
    BEFORE_RECONCILE = "BEFORE_RECONCILE"
    DURING_RECONCILE_READ = "DURING_RECONCILE_READ"
    AFTER_RECONCILE = "AFTER_RECONCILE"
    JOURNAL_SHORT_WRITE = "JOURNAL_SHORT_WRITE"
    JOURNAL_FSYNC_FAILURE = "JOURNAL_FSYNC_FAILURE"
    SNAPSHOT_CORRUPTION = "SNAPSHOT_CORRUPTION"
    LOCK_OWNER_DEATH = "LOCK_OWNER_DEATH"
    LOCK_TOCTOU = "LOCK_TOCTOU"
    SERVICE_TIMEOUT = "SERVICE_TIMEOUT"


class ChaosInjected(RuntimeError):
    def __init__(self, point: FaultPoint):
        self.point = point
        super().__init__(f"test fault injected at {point.value}")


class ChaosController:
    """Default-off controller. Runtime strings are accepted only in test mode."""
    def __init__(self, *, enabled: bool = False,
                 faults: Iterable[FaultPoint] | None = None) -> None:
        self.enabled = bool(enabled)
        self.faults = frozenset(FaultPoint(p) for p in (faults or ()))

    @classmethod
    def from_runtime(cls, value: str | None, *, test_mode: bool = False) -> "ChaosController":
        if not test_mode:
            if value:
                raise ValueError("runtime chaos injection is test-only")
            return cls()
        if not value:
            return cls()
        points = {FaultPoint(part.strip()) for part in value.split(",") if part.strip()}
        return cls(enabled=True, faults=points)

    def hit(self, point: FaultPoint) -> None:
        point = FaultPoint(point)
        if self.enabled and point in self.faults:
            raise ChaosInjected(point)
