"""Immutable models for the limited restart policy."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agent.service_restart_foundation.models import RestartProfile


class ConsumerClass(str, Enum):
    NONE = "NONE"
    PASSIVE = "PASSIVE"
    NON_CRITICAL = "NON_CRITICAL"
    ACTIVE = "ACTIVE"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class BlastRadius(str, Enum):
    RESOURCE = "RESOURCE"
    SERVICE = "SERVICE"
    MULTI_SERVICE = "MULTI_SERVICE"
    HOST = "HOST"
    NETWORK = "NETWORK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AdmissionContext:
    service_id: str
    profile_version: int
    operation: str
    service_class: str
    criticality: str
    identity_verified: bool
    graph_healthy: bool
    dependents: tuple[str, ...]
    consumer: ConsumerClass
    blast_radius: BlastRadius
    quiescence_proven: bool
    startup_proven: bool
    health_contract_complete: bool
    rollback_proven: bool
    pre_health_ok: bool
    approval_valid: bool
    restart_supported: bool = True
    runtime_discovered_unit: str | None = None
    config_valid: bool = True
    risk_acceptable: bool = True
    budget_available: bool = True
    breaker_closed: bool = True
    lock_available: bool = True
    rollout_enabled: bool = True
    old_process_identity: str = ""
    graph_digest: str = ""
    config_digest: str = ""
    health_digest: str = ""
    risk: str = ""
    quiescence_contract: str = ""
    startup_contract: str = ""
    recovery_contract: str = ""
    budget_snapshot: str = ""
    breaker_snapshot: str = ""
    plan_hash: str = ""
    baseline_sha: str = ""
    registry_digest: str = ""


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    reason: str
    step: int


@dataclass(frozen=True)
class RestartExecutionRequest:
    service_id: str
    profile_version: int
    transaction_id: str
    intent_id: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    outcome: str
    adapter_calls: int = 0
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    replayed: bool = False


__all__ = [
    "AdmissionContext", "AdmissionDecision", "BlastRadius", "ConsumerClass",
    "ExecutionResult", "RestartExecutionRequest", "RestartProfile",
]
