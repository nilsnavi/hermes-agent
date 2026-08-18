"""System Boundary Layer data model (Sprint 1.3.3 §5, §10, §11, §21,
§39, §50).

Pure data model — nothing here touches the host. Canonical objects:

- :class:`ResourceClass` (§10) — what resource is touched. UNKNOWN is
  NEVER safe, NEVER USER_DATA, NEVER NONE.
- :class:`OperationClass` (§11) — what operation is performed. Unknown
  mutation is never READ.
- :class:`EffectiveActionClass` — the EFFECTIVE action including
  indirect/chained execution (§12/§14). UNKNOWN is mutation-capable.
- :class:`BoundaryDecision` (§5) — PASS / BLOCK / REVALIDATE_REQUIRED.
  PASS is not permission; BLOCK forbids; REVALIDATE requires a fresh
  preflight.
- :class:`SystemPreflightPlan` (§21) — the immutable preflight record
  bound to tool/capability/operation/target/fingerprint/context.
- :class:`BlastRadius` (§39) — UNKNOWN != NONE.
- :class:`GraphHealth` (§37) — PARTIAL != HEALTHY.
- :class:`REASON_CODES` (§50) — canonical reason-code vocabulary.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── §10 resource classes ────────────────────────────────────────────

class ResourceClass(str, Enum):
    USER_DATA = "USER_DATA"
    APPLICATION_DATA = "APPLICATION_DATA"
    APPLICATION_CONFIG = "APPLICATION_CONFIG"
    SYSTEM_CONFIG = "SYSTEM_CONFIG"
    SYSTEM_BINARY = "SYSTEM_BINARY"
    SYSTEM_SERVICE = "SYSTEM_SERVICE"
    SYSTEM_STATE = "SYSTEM_STATE"
    NETWORK_CONFIG = "NETWORK_CONFIG"
    PACKAGE_STATE = "PACKAGE_STATE"
    PROCESS_RESOURCE = "PROCESS_RESOURCE"
    CONTAINER_RESOURCE = "CONTAINER_RESOURCE"
    DEVICE_RESOURCE = "DEVICE_RESOURCE"
    SECRET_RESOURCE = "SECRET_RESOURCE"
    TEMPORARY = "TEMPORARY"
    UNKNOWN = "UNKNOWN"


#: resource classes that never legitimately appear as a mutation target.
#: (read-only system inspection is fine; writes to these are blocked)
SYSTEM_RESOURCE_CLASSES = frozenset({
    ResourceClass.SYSTEM_CONFIG,
    ResourceClass.SYSTEM_BINARY,
    ResourceClass.SYSTEM_SERVICE,
    ResourceClass.SYSTEM_STATE,
    ResourceClass.NETWORK_CONFIG,
    ResourceClass.PACKAGE_STATE,
    ResourceClass.PROCESS_RESOURCE,
    ResourceClass.CONTAINER_RESOURCE,
    ResourceClass.DEVICE_RESOURCE,
    ResourceClass.SECRET_RESOURCE,
})


# ── §11 operation classes ───────────────────────────────────────────

class OperationClass(str, Enum):
    READ = "READ"
    CREATE = "CREATE"
    WRITE = "WRITE"
    APPEND = "APPEND"
    PATCH = "PATCH"
    DELETE = "DELETE"
    MOVE = "MOVE"
    COPY = "COPY"
    LINK = "LINK"
    PERMISSION_CHANGE = "PERMISSION_CHANGE"
    OWNERSHIP_CHANGE = "OWNERSHIP_CHANGE"
    SERVICE_START = "SERVICE_START"
    SERVICE_STOP = "SERVICE_STOP"
    SERVICE_RESTART = "SERVICE_RESTART"
    SERVICE_ENABLE = "SERVICE_ENABLE"
    SERVICE_DISABLE = "SERVICE_DISABLE"
    PROCESS_START = "PROCESS_START"
    PROCESS_SIGNAL = "PROCESS_SIGNAL"
    PROCESS_KILL = "PROCESS_KILL"
    PACKAGE_INSTALL = "PACKAGE_INSTALL"
    PACKAGE_REMOVE = "PACKAGE_REMOVE"
    PACKAGE_UPGRADE = "PACKAGE_UPGRADE"
    NETWORK_CHANGE = "NETWORK_CHANGE"
    FIREWALL_CHANGE = "FIREWALL_CHANGE"
    IDENTITY_CHANGE = "IDENTITY_CHANGE"
    SECRET_ACCESS = "SECRET_ACCESS"
    CONTAINER_CONTROL = "CONTAINER_CONTROL"
    MOUNT_CONTROL = "MOUNT_CONTROL"
    KERNEL_CONTROL = "KERNEL_CONTROL"
    EXECUTE_SCRIPT = "EXECUTE_SCRIPT"
    EXECUTE_BINARY = "EXECUTE_BINARY"
    UNKNOWN = "UNKNOWN"


#: mutation-capable operation classes (anything that is not a pure READ)
MUTATION_OPERATIONS = frozenset({
    op for op in OperationClass if op is not OperationClass.READ
    and op is not OperationClass.UNKNOWN
})


# ── §12/§14 effective action classes ────────────────────────────────

class EffectiveActionClass(str, Enum):
    READ = "READ"
    WRITE_FILE = "WRITE_FILE"
    DELETE_FILE = "DELETE_FILE"
    MOVE_FILE = "MOVE_FILE"
    PERMISSION_CHANGE = "PERMISSION_CHANGE"
    EXECUTE_SCRIPT = "EXECUTE_SCRIPT"
    EXECUTE_BINARY = "EXECUTE_BINARY"
    SERVICE_CONTROL = "SERVICE_CONTROL"
    SERVICE_RESTART = "SERVICE_RESTART"
    SERVICE_STOP = "SERVICE_STOP"
    PROCESS_CONTROL = "PROCESS_CONTROL"
    PROCESS_KILL = "PROCESS_KILL"
    PROCESS_SELF_CONTROL = "PROCESS_SELF_CONTROL"
    INDIRECT_SYSTEM_CONTROL = "INDIRECT_SYSTEM_CONTROL"
    PACKAGE_CHANGE = "PACKAGE_CHANGE"
    NETWORK_CHANGE = "NETWORK_CHANGE"
    FIREWALL_CHANGE = "FIREWALL_CHANGE"
    CONTAINER_CONTROL = "CONTAINER_CONTROL"
    KERNEL_CONTROL = "KERNEL_CONTROL"
    SECRET_ACCESS = "SECRET_ACCESS"
    UNKNOWN = "UNKNOWN"

    def is_mutation_capable(self) -> bool:
        return self is not EffectiveActionClass.READ


# ── §5 boundary decision ────────────────────────────────────────────

@dataclass(frozen=True)
class BoundaryDecision:
    """§5 — the SBL verdict for one execution attempt.

    verdict: PASS | BLOCK | REVALIDATE_REQUIRED.
    PASS means the SBL adds no prohibition — it is NOT permission.
    BLOCK forbids execution. REVALIDATE_REQUIRED means the target /
    resource / preflight changed and execution is forbidden until a
    fresh preflight.
    """

    verdict: str  # PASS | BLOCK | REVALIDATE_REQUIRED
    reason_code: str = "SBL_OK"
    boundary_version: str = "sbl-v0"
    resource_class: Optional[str] = None
    operation_class: Optional[str] = None
    effective_action_class: Optional[str] = None
    risk_before: Optional[str] = None
    risk_floor: Optional[str] = None
    risk_after: Optional[str] = None
    target_resources: List[str] = field(default_factory=list)
    affected_services: List[str] = field(default_factory=list)
    affected_processes: List[str] = field(default_factory=list)
    affected_ports: List[str] = field(default_factory=list)
    affected_dependencies: List[str] = field(default_factory=list)
    blast_radius: str = "NONE"
    approval_required: bool = False
    validation_required: bool = False
    postcheck_required: bool = False
    resource_fingerprint: Optional[Dict[str, Any]] = None
    preflight_digest: Optional[str] = None
    graph_version: Optional[str] = None
    graph_health: Optional[str] = None
    confidence: Optional[float] = None

    @property
    def allow(self) -> bool:
        return self.verdict == "PASS"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason_code": self.reason_code,
            "boundary_version": self.boundary_version,
            "resource_class": self.resource_class,
            "operation_class": self.operation_class,
            "effective_action_class": self.effective_action_class,
            "risk_before": self.risk_before,
            "risk_floor": self.risk_floor,
            "risk_after": self.risk_after,
            "target_resources": list(self.target_resources),
            "affected_services": list(self.affected_services),
            "affected_processes": list(self.affected_processes),
            "affected_ports": list(self.affected_ports),
            "affected_dependencies": list(self.affected_dependencies),
            "blast_radius": self.blast_radius,
            "approval_required": self.approval_required,
            "validation_required": self.validation_required,
            "postcheck_required": self.postcheck_required,
            "resource_fingerprint": self.resource_fingerprint,
            "preflight_digest": self.preflight_digest,
            "graph_version": self.graph_version,
            "graph_health": self.graph_health,
            "confidence": self.confidence,
        }


#: helper constructors for the common decisions
def pass_decision(reason_code: str = "SBL_OK",
                  **kw: Any) -> BoundaryDecision:
    kw.setdefault("verdict", "PASS")
    kw.setdefault("reason_code", reason_code)
    return BoundaryDecision(**kw)


def block_decision(reason_code: str, **kw: Any) -> BoundaryDecision:
    kw.setdefault("verdict", "BLOCK")
    kw.setdefault("reason_code", reason_code)
    return BoundaryDecision(**kw)


def revalidate_decision(reason_code: str, **kw: Any) -> BoundaryDecision:
    kw.setdefault("verdict", "REVALIDATE_REQUIRED")
    kw.setdefault("reason_code", reason_code)
    return BoundaryDecision(**kw)


# ── §21 preflight plan ──────────────────────────────────────────────

@dataclass(frozen=True)
class SystemPreflightPlan:
    """§21 — immutable preflight plan, cryptographically bound (§22)."""

    preflight_id: str
    execution_id: str
    request_id: str
    run_id: str
    step_id: str
    tool_name: str
    capability: str
    operation_class: str
    effective_action_class: str
    canonical_targets: List[str] = field(default_factory=list)
    arguments_digest: str = ""
    resource_fingerprints: Dict[str, Any] = field(default_factory=dict)
    effective_risk: str = "READ_ONLY"
    risk_floor: str = "READ_ONLY"
    blast_radius: str = "NONE"
    affected_services: List[str] = field(default_factory=list)
    affected_processes: List[str] = field(default_factory=list)
    validators: List[str] = field(default_factory=list)
    post_checks: List[str] = field(default_factory=list)
    rollback_possible: bool = False
    rollback_strategy_metadata: Dict[str, Any] = field(
        default_factory=dict)
    graph_version: Optional[str] = None
    graph_health: Optional[str] = None
    created_at: str = ""
    expires_at: Optional[str] = None
    preflight_digest: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preflight_id": self.preflight_id,
            "execution_id": self.execution_id,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "capability": self.capability,
            "operation_class": self.operation_class,
            "effective_action_class": self.effective_action_class,
            "canonical_targets": list(self.canonical_targets),
            "arguments_digest": self.arguments_digest,
            "resource_fingerprints": dict(self.resource_fingerprints),
            "effective_risk": self.effective_risk,
            "risk_floor": self.risk_floor,
            "blast_radius": self.blast_radius,
            "affected_services": list(self.affected_services),
            "affected_processes": list(self.affected_processes),
            "validators": list(self.validators),
            "post_checks": list(self.post_checks),
            "rollback_possible": self.rollback_possible,
            "rollback_strategy_metadata": dict(
                self.rollback_strategy_metadata),
            "graph_version": self.graph_version,
            "graph_health": self.graph_health,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "preflight_digest": self.preflight_digest,
        }


# ── §39 blast radius ────────────────────────────────────────────────

class BlastRadius(str, Enum):
    NONE = "NONE"
    LOCAL = "LOCAL"
    SERVICE = "SERVICE"
    MULTI_SERVICE = "MULTI_SERVICE"
    HOST = "HOST"
    NETWORK = "NETWORK"
    UNKNOWN = "UNKNOWN"


# ── §37 graph health ────────────────────────────────────────────────

class GraphHealth(str, Enum):
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    CORRUPT = "CORRUPT"


# ── §33 provenance ──────────────────────────────────────────────────

class Provenance(str, Enum):
    STATIC_VERIFIED = "STATIC_VERIFIED"
    RUNTIME_OBSERVED = "RUNTIME_OBSERVED"
    CONFIG_OBSERVED = "CONFIG_OBSERVED"
    INFERRED = "INFERRED"
    LEARNED = "LEARNED"


# ── §50 reason codes ────────────────────────────────────────────────

REASON_CODES = frozenset({
    "SBL_OK",
    "RESOURCE_UNKNOWN",
    "RESOURCE_SYSTEM",
    "RESOURCE_CHANGED_AFTER_PREFLIGHT",
    "PATH_UNRESOLVED",
    "PATH_ESCAPE_DETECTED",
    "SYMLINK_ESCAPE",
    "OPERATION_UNKNOWN",
    "EFFECTIVE_ACTION_UNKNOWN",
    "INDIRECT_SYSTEM_CONTROL",
    "PROCESS_SELF_CONTROL_FORBIDDEN",
    "NETWORK_TARGET_UNKNOWN",
    "SECRET_RESOURCE_DETECTED",
    "BOUNDARY_BYPASS_DETECTED",
    "DEPENDENCY_UNKNOWN",
    "BLAST_RADIUS_UNKNOWN",
    "BLAST_RADIUS_HIGH",
    "SERVICE_GRAPH_STALE",
    "SERVICE_GRAPH_PARTIAL",
    "SERVICE_GRAPH_UNAVAILABLE",
    "SERVICE_GRAPH_CORRUPT",
    "PREFLIGHT_REQUIRED",
    "PREFLIGHT_EXPIRED",
    "PREFLIGHT_MISMATCH",
    "VALIDATION_REQUIRED",
    "VALIDATION_UNAVAILABLE",
    "POSTCHECK_REQUIRED",
    "SBL_INTERNAL_ERROR",
})


# ── effective action result ─────────────────────────────────────────

@dataclass(frozen=True)
class EffectiveActionResult:
    """Result of classifying a command/script/artifact."""

    effective_action_class: EffectiveActionClass
    operation_class: OperationClass
    targets: List[str] = field(default_factory=list)
    self_control: bool = False
    is_mutation: bool = False
    wrappers: List[str] = field(default_factory=list)
    confidence: Optional[float] = None

    @property
    def is_system_control(self) -> bool:
        return self.effective_action_class in (
            EffectiveActionClass.SERVICE_CONTROL,
            EffectiveActionClass.SERVICE_RESTART,
            EffectiveActionClass.SERVICE_STOP,
            EffectiveActionClass.INDIRECT_SYSTEM_CONTROL,
            EffectiveActionClass.PROCESS_CONTROL,
            EffectiveActionClass.PROCESS_KILL,
            EffectiveActionClass.PROCESS_SELF_CONTROL,
        )


__all__ = [
    "ResourceClass",
    "SYSTEM_RESOURCE_CLASSES",
    "OperationClass",
    "MUTATION_OPERATIONS",
    "EffectiveActionClass",
    "BoundaryDecision",
    "pass_decision",
    "block_decision",
    "revalidate_decision",
    "SystemPreflightPlan",
    "BlastRadius",
    "GraphHealth",
    "Provenance",
    "REASON_CODES",
    "EffectiveActionResult",
]
