"""Sprint 1.3.13 — single aux service restart canary (models).

Immutable plan + single-use approval + typed execution request + enums.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class RestartOutcome(Enum):
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    DENIED = "DENIED"
    DUPLICATE = "DUPLICATE_ALREADY_COMMITTED"
    CANARY_DISABLED = "CANARY_DISABLED"


class Operation(Enum):
    RESTART = "RESTART"
    STOP = "STOP"
    START = "START"
    KILL = "KILL"
    SIGNAL = "SIGNAL"


class CanaryState(Enum):
    CREATED = "CREATED"
    APPROVED = "APPROVED"
    PREFLIGHT_OK = "PREFLIGHT_OK"
    LOCKED = "LOCKED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    STABILIZED = "STABILIZED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ServiceRestartCanaryPlan:
    """Immutable restart plan bound to profile/identity/graph/config/approval."""

    transaction_id: str
    service_id: str
    profile_version: int
    operation: str = "RESTART"
    old_process_identity: str = ""
    identity_fingerprint: str = ""
    graph_digest: str = ""
    config_hash: str = ""
    ports_before: tuple = field(default_factory=tuple)
    pre_health_receipt: str = ""
    approval_id: str = ""
    risk: str = "HIGH"
    blast_radius: str = "SERVICE"
    stop_contract: str = ""
    quiescence_contract: str = ""
    start_contract: str = ""
    post_health_contract: str = ""
    recovery_strategy: str = "MANUAL_REVIEW_REQUIRED"
    created_at: float = 0.0
    expires_at: float = 0.0

    def expired(self, now: float) -> bool:
        return bool(self.expires_at) and now > self.expires_at


@dataclass(frozen=True)
class RestartApproval:
    approval_id: str
    service_id: str
    profile_version: int
    operation: str = "RESTART"
    old_pid_identity: str = ""
    old_start_identity: str = ""
    graph_digest: str = ""
    ports: tuple = field(default_factory=tuple)
    config_hash: str = ""
    pre_health: str = "HEALTHY"
    risk: str = "HIGH"
    blast_radius: str = "SERVICE"
    quiescence_contract: str = ""
    startup_contract: str = ""
    rollback_plan: str = ""
    baseline_sha: str = ""
    plan_hash: str = ""
    ttl: float = 300.0
    created_at: float = 0.0
    used: bool = False
    transaction_id: str = ""


@dataclass(frozen=True)
class RestartExecutionRequest:
    """Typed request accepted by the executor. No raw commands/units/shell."""

    service_id: str
    verified_unit_identity: str
    transaction_id: str

    def verify(self, expected_service: str, expected_unit: str) -> bool:
        return (
            self.service_id == expected_service
            and self.verified_unit_identity == expected_unit
            and bool(self.transaction_id)
        )


# STABLE state names for durable journal.
EVENT_PLANNED = "RESTART_PLANNED"
EVENT_PREFLIGHT_OK = "RESTART_PREFLIGHT_OK"
EVENT_APPROVED = "RESTART_APPROVED"
EVENT_LOCK_ACQUIRED = "RESTART_LOCK_ACQUIRED"
EVENT_STARTED = "RESTART_STARTED"
EVENT_ADAPTER_CALL = "RESTART_ADAPTER_CALL"
EVENT_OLD_GONE = "RESTART_OLD_GONE"
EVENT_QUIESCENT = "RESTART_QUIESCENT"
EVENT_NEW_VERIFIED = "RESTART_NEW_VERIFIED"
EVENT_PORTS_OK = "RESTART_PORTS_OK"
EVENT_STABILIZED = "RESTART_STABILIZED"
EVENT_COMMITTED = "RESTART_COMMITTED"
EVENT_DUPLICATE = "RESTART_DUPLICATE"
EVENT_UNKNOWN_OUTCOME = "RESTART_UNKNOWN_OUTCOME"


__all__ = [
    "CanaryState",
    "Operation",
    "RestartApproval",
    "RestartExecutionRequest",
    "RestartOutcome",
    "ServiceRestartCanaryPlan",
]