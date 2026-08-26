"""Phase 6 — First Read-Only System Agents Integration vertical.

The first end-to-end Agent Platform contour: a CONTROL-PLANE read-only chain.
Every module here is a pure domain contract or a compose-able runtime; none of
them executes a tool, grants a capability, mutates policy, or touches a network
source (network read-only stays DENIED by default). The only read site in the
vertical is an injected ReadOnlyProvider reached solely after a capability was
admitted by the SecurityBoundary AND a runtime grant authorized the call.

Invariants (auditable):
  * read-only capability allowlist is a closed enum (no READ_ANYTHING);
  * registry is runtime-owned and sealed (drift -> DENY);
  * run is bound to tenant/user/task/step/agent/generation (cross-tenant DENY);
  * memory arrives only via the gateway Top-K pipeline (redacted/sanitized);
  * remote/network read-only is DENIED by default until certified;
  * messages and payloads are canonical data (ORCH-001/002 closed upstream);
  * supervisor excludes the failed agent on alternative routes (ORCH-003);
  * audit events are bound, append-only DATA (never authority).
"""

from .agent_run import (
    AgentRun,
    AgentRunKey,
    AgentRunRegistry,
    RunIsolationError,
    digest_of,
)
from .agents import (
    CodingShadowAgent,
    MemoryAgent,
    MemoryProposal,
    MonitoringAgent,
    PatchProposal,
    PlannerAgent,
    ResearchAgent,
    ReviewVerdict,
    ReviewerAgent,
)
from .audit_store import (
    AuditError,
    AuditStoreFull,
    ExecutionAuditEvent,
    InMemoryAuditStore,
    PersistentAuditStore,
    build_audit_event,
    new_run_provenance,
)
from .capabilities import (
    NETWORK_READ_ONLY_DEFAULT_DENIED,
    READ_ONLY_ALLOWLIST,
    CapabilityAccessClass,
    ReadOnlyCapability,
    access_class,
    is_read_only_allowed,
    side_effect_for,
)
from .context import AgentContextAssembler, AssembledAgentContext, MemoryPortal
from .error_taxonomy import NON_SUCCESS_OUTCOMES, AgentOutcome
from .gate_token import (
    GrantDenied,
    OpaqueGrant,
    RuntimeGrantSeal,
    copy_is_denied,
)
from .metrics import METRIC_NAMES, MetricsRegistry
from .network_policy import (
    NetworkPolicyError,
    NetworkPolicyVerdict,
    NetworkReadOnlyPolicy,
)
from .readonly_routing import (
    NoReadOnlyRoute,
    READONLY_AGENT_CAPABILITIES,
    ReadOnlyRoute,
    ReadOnlyRouter,
    SealedRegistry,
)
from .result import AgentObservation, Citation
from .supervisor_state import (
    AgentRunState,
    AgentRunStateMachine,
    InvalidRunTransition,
    RetryVerdict,
    bounded_retry_decision,
    exclude_failed,
)
from .vertical import (
    ReadOnlyAgentVertical,
    ReadOnlyProvider,
    VerticalResult,
    build_read_only_gate,
)

__all__ = [
    "AgentContextAssembler",
    "AgentObservation",
    "AgentOutcome",
    "AgentRun",
    "AgentRunKey",
    "AgentRunRegistry",
    "AgentRunState",
    "AgentRunStateMachine",
    "AssembledAgentContext",
    "AuditError",
    "AuditStoreFull",
    "CapabilityAccessClass",
    "Citation",
    "CodingShadowAgent",
    "ExecutionAuditEvent",
    "GrantDenied",
    "InMemoryAuditStore",
    "InvalidRunTransition",
    "MemoryAgent",
    "MemoryPortal",
    "MemoryProposal",
    "METRIC_NAMES",
    "MonitoringAgent",
    "NON_SUCCESS_OUTCOMES",
    "NETWORK_READ_ONLY_DEFAULT_DENIED",
    "NetworkPolicyError",
    "NetworkPolicyVerdict",
    "NetworkReadOnlyPolicy",
    "NoReadOnlyRoute",
    "OpaqueGrant",
    "PatchProposal",
    "PersistentAuditStore",
    "PlannerAgent",
    "READ_ONLY_ALLOWLIST",
    "READONLY_AGENT_CAPABILITIES",
    "ReadOnlyAgentVertical",
    "ReadOnlyCapability",
    "ReadOnlyProvider",
    "ReadOnlyRoute",
    "ReadOnlyRouter",
    "ResearchAgent",
    "RetryVerdict",
    "ReviewVerdict",
    "ReviewerAgent",
    "RunIsolationError",
    "RuntimeGrantSeal",
    "SealedRegistry",
    "VerticalResult",
    "access_class",
    "bounded_retry_decision",
    "build_audit_event",
    "build_read_only_gate",
    "copy_is_denied",
    "digest_of",
    "exclude_failed",
    "is_read_only_allowed",
    "new_run_provenance",
    "side_effect_for",
]