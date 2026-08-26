"""Execution Boundary & Coding Agent Security Hardening — Phase 5.

Certifies the SINGLE admissible execution path between the Agent Platform
Control Plane and the existing Hermes Execution Kernel:

    AgentCapabilityIntent
      -> platform_policy (PolicyEvaluator)
      -> capability_router (CapabilityRouterSeam)
      -> SystemBoundary (SystemBoundarySeam)
      -> VerifiedToolExecutor (ToolExecutorSeam)
      -> SandboxAdapter (SealedSandbox)

No alternative path exists in this layer: no Agent->adapter, no
Agent->executor-direct, no planner/supervisor/message-bus/memory -> tool.

Invariants (auditable):

* every pipeline stage is MANDATORY -- missing/errored component => DENY;
* caller-supplied verdicts/approvals are DATA ONLY -- the gate computes
  authority itself from the mandatory components at admission time;
* REVALIDATE_REQUIRED / UNKNOWN / TIMEOUT / MISSING_EVIDENCE => no execution;
* SIDE_EFFECT_UNKNOWN => HUMAN_REVIEW (never auto-execute);
* mutation side-effect classes and CodingAgent write/execute are hard-denied;
* the sandbox adapter is runtime-owned and sealed (direct call DENIED);
* audit records are append-only DATA, never authority.

This package imports NO execution-kernel code and performs NO tool execution.
"""

from .admission import AdmissionDecision, SecurityBoundaryGate
from .audit import AuditTrail, ExecutionAuditRecord
from .coding import (
    CODING_FORBIDDEN_CAPABILITIES,
    CODING_READ_ONLY_CAPABILITIES,
    classify_side_effect,
    is_forbidden_capability,
    is_read_only_capability,
)
from .exceptions import (
    AdmissionDenied,
    CallerVerdictRejected,
    ComponentMissing,
    RegistryDrift,
    SealViolation,
    SecurityBoundaryError,
    UnknownImplementation,
)
from .intent import AgentCapabilityIntent, CallerClaim
from .ports import (
    CapabilityRouterSeam,
    PolicyEvaluator,
    SandboxAdapterSeam,
    SystemBoundarySeam,
    ToolExecutorSeam,
    side_effect_of_operation,
)
from .seal import SealedSandbox
from .status import (
    AdmissionOutcome,
    Disposition,
    NON_EXECUTABLE_DISPOSITIONS,
    SideEffectClass,
)

__all__ = [
    "AdmissionDecision",
    "AdmissionDenied",
    "AdmissionOutcome",
    "AuditTrail",
    "CallerClaim",
    "CallerVerdictRejected",
    "CODING_FORBIDDEN_CAPABILITIES",
    "CODING_READ_ONLY_CAPABILITIES",
    "ComponentMissing",
    "Disposition",
    "ExecutionAuditRecord",
    "NON_EXECUTABLE_DISPOSITIONS",
    "PolicyEvaluator",
    "RegistryDrift",
    "SealViolation",
    "SealedSandbox",
    "SecurityBoundaryError",
    "SecurityBoundaryGate",
    "SideEffectClass",
    "SystemBoundarySeam",
    "ToolExecutorSeam",
    "UnknownImplementation",
    "AgentCapabilityIntent",
    "CapabilityRouterSeam",
    "SandboxAdapterSeam",
    "classify_side_effect",
    "is_forbidden_capability",
    "is_read_only_capability",
    "side_effect_of_operation",
]