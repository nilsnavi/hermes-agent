"""Phase 7 -- Shadow Runtime & Observability (control plane, no production effect).

Bounded package that runs COPIES of production tasks through the Phase 6 read-only
vertical under a shadow lens: sampling, plan, route, claim, context, capability
intent, security boundary, read observation, supervisor disposition, comparison,
audit/metrics/tracing. Shadow output is DATA (``ShadowDecision``) only. It can
never return or mutate a production response, call a production executor, grant
capabilities, change scheduler/provider/config, or become authority.

Production activation is OFF in Phase 7 (no live hook).
"""

from .audit import (
    SHADOW_AUDIT_CHAIN_ORDER,
    ShadowAuditEvent,
    ShadowAuditKind,
    ShadowAuditStore,
)
from .claim_store import (
    ClaimState,
    InMemoryClaimStore,
    ShadowClaim,
    ShadowClaimStore,
)
from .comparison import ComparisonEngine, ComparisonResult
from .dispatcher import ShadowDispatcher
from .exceptions import (
    ShadowClaimError,
    ShadowError,
    ShadowIsolationError,
    ShadowOverloaded,
    ShadowSamplingError,
    ShadowTimeout,
)
from .guards import IsolationGuard, ShadowBudget, TimeBudget
from .models import (
    ComparisonClass,
    ShadowDecision,
    ShadowSamplingMode,
    ShadowTaskEnvelope,
)
from .observability import (
    SHADOW_METRIC_NAMES,
    ShadowMetrics,
    ShadowSpan,
    ShadowTracer,
)
from .runtime import (
    ShadowRunOutcome,
    ShadowRuntime,
    default_capability_for,
    default_plan,
    shadow_semantic_key,
)
from .sampling import SamplingResult, ShadowSampler

# Mechanical isolation marker: this package can never affect production.
SHADOW_CANNOT_AFFECT_PRODUCTION = True
PRODUCTION_ACTIVATION = False
SHADOW_MEMORY_WRITES = False  # Phase 7 default: OFF

__all__ = [
    "ClaimState",
    "ComparisonClass",
    "ComparisonEngine",
    "ComparisonResult",
    "InMemoryClaimStore",
    "IsolationGuard",
    "PRODUCTION_ACTIVATION",
    "SHADOW_AUDIT_CHAIN_ORDER",
    "SHADOW_CANNOT_AFFECT_PRODUCTION",
    "SHADOW_MEMORY_WRITES",
    "SHADOW_METRIC_NAMES",
    "SamplingResult",
    "ShadowAuditEvent",
    "ShadowAuditKind",
    "ShadowAuditStore",
    "ShadowBudget",
    "ShadowClaim",
    "ShadowClaimError",
    "ShadowClaimStore",
    "ShadowDecision",
    "ShadowDispatcher",
    "ShadowError",
    "ShadowIsolationError",
    "ShadowMetrics",
    "ShadowOverloaded",
    "ShadowRunOutcome",
    "ShadowRuntime",
    "ShadowSampler",
    "ShadowSamplingError",
    "ShadowSamplingMode",
    "ShadowSpan",
    "ShadowTaskEnvelope",
    "ShadowTimeout",
    "ShadowTracer",
    "TimeBudget",
    "default_capability_for",
    "default_plan",
    "shadow_semantic_key",
]