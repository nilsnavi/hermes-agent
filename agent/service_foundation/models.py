"""Sprint 1.3.9 — models: enums + immutable ServiceProfile + HealthContract + Plan."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ServiceClass(str, Enum):
    HERMES_CORE = "hermes_core"
    HERMES_AUXILIARY = "hermes_auxiliary"
    DATASTORE = "datastore"
    SCHEDULER = "scheduler"
    PROVIDER = "provider"
    NETWORK = "network"
    SECURITY = "security"
    OBSERVABILITY = "observability"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class Operation(str, Enum):
    INSPECT = "inspect"
    STATUS = "status"
    HEALTH_CHECK = "health_check"
    CONFIG_VALIDATE = "config_validate"
    RELOAD_ELIGIBILITY = "reload_eligibility"
    RESTART_ELIGIBILITY = "restart_eligibility"
    STOP_ELIGIBILITY = "stop_eligibility"
    START_ELIGIBILITY = "start_eligibility"
    EXEC_RELOAD = "reload"
    EXEC_RESTART = "restart"
    EXEC_STOP = "stop"
    EXEC_START = "start"


_EXEC_OPS = {Operation.EXEC_RELOAD, Operation.EXEC_RESTART, Operation.EXEC_STOP, Operation.EXEC_START}


def is_exec_operation(op: Operation) -> bool:
    return op in _EXEC_OPS


class IdentityResult(str, Enum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ValidatorResult(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class GraphStatus(str, Enum):
    HEALTHY = "healthy"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    CORRUPT = "corrupt"


class Provenance(str, Enum):
    STATIC_VERIFIED = "static_verified"
    SYSTEMD_DECLARED = "systemd_declared"
    RUNTIME_OBSERVED = "runtime_observed"
    CONFIG_OBSERVED = "config_observed"
    INFERRED = "inferred"
    LEARNED = "learned"


class EdgeType(str, Enum):
    REQUIRES = "requires"
    WANTS = "wants"
    AFTER = "after"
    BEFORE = "before"
    PART_OF = "part_of"
    BINDS_TO = "binds_to"
    TRIGGERED_BY = "triggered_by"
    CONSUMED_BY = "consumed_by"
    OBSERVED_DEPENDENCY = "observed_dependency"


class Criticality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BlastRadius(str, Enum):
    NONE = "none"
    RESOURCE_ONLY = "resource_only"
    SERVICE = "service"
    MULTI_SERVICE = "multi_service"
    HOST = "host"
    NETWORK = "network"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class RiskClass(str, Enum):
    NO_MUTATION = "no_mutation"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SelfControlClass(str, Enum):
    SELF_CONTROL_FORBIDDEN = "self_control_forbidden"
    NORMAL = "normal"


class Eligibility(str, Enum):
    ELIGIBLE_FOR_FUTURE_RELOAD_CANARY = "eligible_for_future_reload_canary"
    ELIGIBLE_FOR_FUTURE_RESTART_CANARY = "eligible_for_future_restart_canary"
    REQUIRES_APPROVAL = "requires_approval"
    REQUIRES_OPERATOR = "requires_operator"
    SELF_CONTROL_FORBIDDEN = "self_control_forbidden"
    SERVICE_CLASS_DENIED = "service_class_denied"
    IDENTITY_UNVERIFIED = "identity_unverified"
    DEPENDENCY_RISK_TOO_HIGH = "dependency_risk_too_high"
    BLAST_RADIUS_TOO_HIGH = "blast_radius_too_high"
    HEALTH_CONTRACT_MISSING = "health_contract_missing"
    CONFIG_VALIDATOR_MISSING = "config_validator_missing"
    ROLLBACK_UNPROVEN = "rollback_unproven"
    GRAPH_STALE = "graph_stale"
    GRAPH_UNKNOWN = "graph_unknown"
    OPERATION_UNSUPPORTED = "operation_unsupported"
    POLICY_DENIED = "policy_denied"
    REVALIDATE_REQUIRED = "revalidate_required"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HealthContract:
    health_contract_id: str
    service_id: str
    checks: tuple[str, ...] = ("systemd_active", "pid_alive")
    timeout_s: float = 10.0
    stabilization_window_s: float = 5.0


@dataclass(frozen=True)
class ConfigValidator:
    validator_id: str
    service_id: str
    kind: str = "json_schema"
    allowlist: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServiceProfile:
    service_id: str
    profile_version: int
    unit_name: str
    service_manager: str = "systemd"
    service_scope: str = "user"
    expected_user: str = ""
    expected_group: str = ""
    expected_executable: str = ""
    expected_exec_start: str = ""
    expected_exec_reload: str = ""
    service_class: ServiceClass = ServiceClass.UNKNOWN
    criticality: Criticality = Criticality.MEDIUM
    self_control_class: SelfControlClass = SelfControlClass.NORMAL
    dependencies: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()
    expected_ports: tuple[str, ...] = ()
    expected_process_pattern: str = ""
    health_contract_id: str = ""
    config_validator_id: str = ""
    reload_supported: bool = False
    restart_supported: bool = False
    rollback_strategy: str = "unsupported"
    risk_class: RiskClass = RiskClass.NO_MUTATION
    blast_radius_ceiling: BlastRadius = BlastRadius.NONE
    enabled: bool = True
    created_at: str = ""


@dataclass(frozen=True)
class ServiceChangePlan:
    plan_id: str
    service_id: str
    profile_version: int
    operation: Operation
    identity_fingerprint: str
    dependency_graph_digest: str
    health_contract_id: str
    validator_id: str
    risk: RiskClass
    blast_radius: BlastRadius
    approval_required: bool
    rollback_strategy: str
    expected_pre_state: str
    expected_post_state: str
    created_at: float = 0.0
    expires_at: float = 0.0
