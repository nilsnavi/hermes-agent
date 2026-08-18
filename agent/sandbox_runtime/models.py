"""Sandbox mutation models (Sprint 1.3.5 §6/§7/§12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from .exceptions import PlanChangedAfterApproval, SandboxModelError


class SandboxOperation(str, Enum):
    """The ONLY supported mutation surface (§5)."""

    CREATE_FILE = "CREATE_FILE"
    WRITE_FILE = "WRITE_FILE"
    REPLACE_FILE = "REPLACE_FILE"
    DELETE_FILE = "DELETE_FILE"
    RENAME_FILE = "RENAME_FILE"
    CREATE_DIRECTORY = "CREATE_DIRECTORY"
    DELETE_EMPTY_DIRECTORY = "DELETE_EMPTY_DIRECTORY"
    CHMOD = "CHMOD"
    WRITE_TEST_CONFIG = "WRITE_TEST_CONFIG"
    START_SANDBOX_SERVICE = "START_SANDBOX_SERVICE"
    STOP_SANDBOX_SERVICE = "STOP_SANDBOX_SERVICE"
    RESTART_SANDBOX_SERVICE = "RESTART_SANDBOX_SERVICE"
    RELOAD_SANDBOX_SERVICE = "RELOAD_SANDBOX_SERVICE"


class ResourceType(str, Enum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"
    PERMISSION = "PERMISSION"
    CONFIG = "CONFIG"
    SERVICE = "SERVICE"


class RiskClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TransactionState(str, Enum):
    # happy path
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    PREFLIGHT_OK = "PREFLIGHT_OK"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    SNAPSHOT_CREATED = "SNAPSHOT_CREATED"
    LOCK_ACQUIRED = "LOCK_ACQUIRED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    HEALTH_CHECKING = "HEALTH_CHECKING"
    COMMITTED = "COMMITTED"
    # error branches
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    BACKUP_FAILED = "BACKUP_FAILED"
    LOCK_FAILED = "LOCK_FAILED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    VERIFY_FAILED = "VERIFY_FAILED"
    HEALTH_FAILED = "HEALTH_FAILED"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_VERIFY_FAILED = "ROLLBACK_VERIFY_FAILED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    CANCELLED = "CANCELLED"
    DENIED = "DENIED"


#: Legal transitions — every other pair is illegal (§12).
LEGAL_TRANSITIONS: Dict[TransactionState, set] = {
    TransactionState.CREATED: {TransactionState.PLANNED,
                               TransactionState.CANCELLED},
    TransactionState.PLANNED: {TransactionState.PREFLIGHT_OK,
                               TransactionState.PREFLIGHT_FAILED,
                               TransactionState.CANCELLED},
    TransactionState.PREFLIGHT_OK: {TransactionState.WAITING_APPROVAL,
                                    TransactionState.APPROVED,
                                    TransactionState.CANCELLED},
    TransactionState.WAITING_APPROVAL: {TransactionState.APPROVED,
                                        TransactionState.APPROVAL_DENIED,
                                        TransactionState.APPROVAL_EXPIRED,
                                        TransactionState.CANCELLED},
    TransactionState.APPROVED: {TransactionState.SNAPSHOT_CREATED,
                                TransactionState.BACKUP_FAILED,
                                TransactionState.CANCELLED},
    TransactionState.SNAPSHOT_CREATED: {TransactionState.LOCK_ACQUIRED,
                                        TransactionState.LOCK_FAILED,
                                        TransactionState.CANCELLED},
    TransactionState.LOCK_ACQUIRED: {TransactionState.EXECUTING,
                                     TransactionState.ROLLBACK_REQUIRED,
                                     TransactionState.CANCELLED},
    TransactionState.EXECUTING: {TransactionState.EXECUTED,
                                 TransactionState.EXECUTION_FAILED,
                                 TransactionState.UNKNOWN_OUTCOME},
    TransactionState.EXECUTED: {TransactionState.VERIFYING,
                                TransactionState.VERIFY_FAILED,
                                TransactionState.UNKNOWN_OUTCOME},
    TransactionState.VERIFYING: {TransactionState.VERIFIED,
                                 TransactionState.VERIFY_FAILED},
    TransactionState.VERIFIED: {TransactionState.HEALTH_CHECKING,
                                TransactionState.HEALTH_FAILED},
    TransactionState.HEALTH_CHECKING: {TransactionState.COMMITTED,
                                       TransactionState.HEALTH_FAILED},
    # error/rollback branches
    TransactionState.PREFLIGHT_FAILED: {TransactionState.CANCELLED},
    TransactionState.APPROVAL_DENIED: {TransactionState.CANCELLED},
    TransactionState.APPROVAL_EXPIRED: {TransactionState.CANCELLED},
    TransactionState.BACKUP_FAILED: {TransactionState.CANCELLED},
    TransactionState.LOCK_FAILED: {TransactionState.CANCELLED},
    TransactionState.EXECUTION_FAILED: {TransactionState.ROLLBACK_REQUIRED,
                                        TransactionState.MANUAL_REVIEW_REQUIRED},
    TransactionState.UNKNOWN_OUTCOME: {TransactionState.MANUAL_REVIEW_REQUIRED},
    TransactionState.VERIFY_FAILED: {TransactionState.ROLLBACK_REQUIRED},
    TransactionState.HEALTH_FAILED: {TransactionState.ROLLBACK_REQUIRED},
    TransactionState.ROLLBACK_REQUIRED: {TransactionState.ROLLING_BACK,
                                         TransactionState.MANUAL_REVIEW_REQUIRED},
    TransactionState.ROLLING_BACK: {TransactionState.ROLLED_BACK,
                                    TransactionState.ROLLBACK_VERIFY_FAILED},
    TransactionState.ROLLED_BACK: set(),
    TransactionState.ROLLBACK_VERIFY_FAILED: {TransactionState.MANUAL_REVIEW_REQUIRED},
    TransactionState.MANUAL_REVIEW_REQUIRED: set(),
    TransactionState.CANCELLED: set(),
    TransactionState.DENIED: set(),
}

#: Terminal states — no further transitions.
TERMINAL_STATES = {
    TransactionState.COMMITTED,
    TransactionState.ROLLED_BACK,
    TransactionState.ROLLBACK_VERIFY_FAILED,
    TransactionState.MANUAL_REVIEW_REQUIRED,
    TransactionState.CANCELLED,
    TransactionState.DENIED,
}

#: States that are error branches (used by the pipeline).
TRANSACTION_STATE_ERRORS = {
    TransactionState.PREFLIGHT_FAILED,
    TransactionState.APPROVAL_DENIED,
    TransactionState.APPROVAL_EXPIRED,
    TransactionState.BACKUP_FAILED,
    TransactionState.LOCK_FAILED,
    TransactionState.EXECUTION_FAILED,
    TransactionState.UNKNOWN_OUTCOME,
    TransactionState.VERIFY_FAILED,
    TransactionState.HEALTH_FAILED,
    TransactionState.ROLLBACK_REQUIRED,
    TransactionState.ROLLBACK_VERIFY_FAILED,
    TransactionState.MANUAL_REVIEW_REQUIRED,
    TransactionState.DENIED,
}


@dataclass(frozen=True)
class SandboxMutationRequest:
    """Strict mutation request model (§6). No arbitrary kwargs."""

    request_id: str
    run_id: str
    step_id: str
    operation: str
    resource_type: str
    target: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    expected_state: Optional[str] = None
    expected_hash: Optional[str] = None
    risk_class: str = "MEDIUM"
    side_effect: str = "MUTATION"
    policy_version: str = "cap-policy-v1"
    boundary_version: str = "sbl-v1"
    requested_by: str = "unknown"
    approval_id: Optional[str] = None
    created_at: Optional[str] = None
    ttl: float = 300.0
    idempotency_key: str = ""

    _KNOWN_FIELDS = {
        "request_id", "run_id", "step_id", "operation", "resource_type",
        "target", "arguments", "expected_state", "expected_hash",
        "risk_class", "side_effect", "policy_version", "boundary_version",
        "requested_by", "approval_id", "created_at", "ttl", "idempotency_key",
    }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SandboxMutationRequest":
        unknown = set(data) - cls._KNOWN_FIELDS
        if unknown:
            raise SandboxModelError(
                f"unknown request fields: {sorted(unknown)}")
        allowed = {k: v for k, v in data.items() if k in cls._KNOWN_FIELDS}
        return cls(**allowed)

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self._KNOWN_FIELDS}

    def validate(self) -> bool:
        """Structural validation — fail closed on any anomaly."""
        if not self.request_id or not self.run_id or not self.step_id:
            return False
        if not self.idempotency_key:
            return False
        if self.ttl <= 0:
            return False
        if self.operation not in {o.value for o in SandboxOperation}:
            return False
        if self.resource_type not in {r.value for r in ResourceType}:
            return False
        # operation / resource-type compatibility (§5)
        compat = {
            SandboxOperation.CREATE_FILE.value: ResourceType.FILE.value,
            SandboxOperation.WRITE_FILE.value: ResourceType.FILE.value,
            SandboxOperation.REPLACE_FILE.value: ResourceType.FILE.value,
            SandboxOperation.DELETE_FILE.value: ResourceType.FILE.value,
            SandboxOperation.RENAME_FILE.value: ResourceType.FILE.value,
            SandboxOperation.CREATE_DIRECTORY.value: ResourceType.DIRECTORY.value,
            SandboxOperation.DELETE_EMPTY_DIRECTORY.value: ResourceType.DIRECTORY.value,
            SandboxOperation.CHMOD.value: ResourceType.PERMISSION.value,
            SandboxOperation.WRITE_TEST_CONFIG.value: ResourceType.CONFIG.value,
            SandboxOperation.START_SANDBOX_SERVICE.value: ResourceType.SERVICE.value,
            SandboxOperation.STOP_SANDBOX_SERVICE.value: ResourceType.SERVICE.value,
            SandboxOperation.RESTART_SANDBOX_SERVICE.value: ResourceType.SERVICE.value,
            SandboxOperation.RELOAD_SANDBOX_SERVICE.value: ResourceType.SERVICE.value,
        }
        return compat.get(self.operation) == self.resource_type


@dataclass(frozen=True)
class SandboxMutationPlan:
    """Immutable mutation plan (§7). Locked after approval."""

    plan_id: str
    request_id: str
    resolved_target: str
    operation: str
    resource_type: str
    before_state: Optional[str]
    expected_after_state: Optional[str]
    risk: str
    approval_required: bool
    backup_required: bool
    verification_strategy: str
    rollback_strategy: str
    health_strategy: str
    preflight_fingerprint: str
    created_at: str
    expires_at: Optional[str] = None
    _approved: bool = False

    @property
    def approved(self) -> bool:
        return self._approved

    def lock_after_approval(self) -> None:
        object.__setattr__(self, "_approved", True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "request_id": self.request_id,
            "resolved_target": self.resolved_target,
            "operation": self.operation,
            "resource_type": self.resource_type,
            "before_state": self.before_state,
            "expected_after_state": self.expected_after_state,
            "risk": self.risk,
            "approval_required": self.approval_required,
            "backup_required": self.backup_required,
            "verification_strategy": self.verification_strategy,
            "rollback_strategy": self.rollback_strategy,
            "health_strategy": self.health_strategy,
            "preflight_fingerprint": self.preflight_fingerprint,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "approved": self._approved,
        }


def plan_changed_after_approval(plan: SandboxMutationPlan,
                                field_name: str, new_value: Any) -> None:
    """§7 — a locked plan must never change after approval."""
    raise PlanChangedAfterApproval(
        f"plan {plan.plan_id} is immutable after approval "
        f"({field_name} change refused)")


#: Operation → required expected_state for preflight.
OPERATION_EXPECTED_PRESENT = {
    SandboxOperation.CREATE_FILE.value: False,
    SandboxOperation.WRITE_FILE.value: True,
    SandboxOperation.REPLACE_FILE.value: True,
    SandboxOperation.DELETE_FILE.value: True,
    SandboxOperation.RENAME_FILE.value: True,
    SandboxOperation.CREATE_DIRECTORY.value: False,
    SandboxOperation.DELETE_EMPTY_DIRECTORY.value: True,
    SandboxOperation.CHMOD.value: True,
    SandboxOperation.WRITE_TEST_CONFIG.value: True,
}
