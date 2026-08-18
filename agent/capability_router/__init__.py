"""Capability Router V2 (Sprint 1.3.0) — FOUNDATION.

Single routing layer that takes an Intent Router decision (intent +
subtype) and selects a VERIFIED capability/tool via registry + policy:

    Intent Router
         ↓
    CapabilityResolver      intent/subtype → CapabilityRequirement
         ↓
    CapabilityRegistry      static verified capability descriptors
         ↓
    CapabilityPolicyEngine  fail-closed precedence ladder
         ↓
    CapabilityRouteDecision V2 | LEGACY | DENY (+ tool, reason)
         ↓
    Execution Adapter       gateway V2 canary path (unchanged)

Sprint 1.3.0 does NOT expand production authority: the set of V2-routable
intents after this sprint is EXACTLY the Sprint 1.2.4 set — STATUS_READ
(per-subtype verified tools) and SEARCH_READ (limited production
allowlist). Everything else stays LEGACY.

Design rules:

- Registry is STATIC and EXPLICIT: no dynamic arbitrary tool discovery.
- Resolver is DETERMINISTIC: no LLM, no network, no DB.
- Policy is FAIL-CLOSED with the §9 precedence: unsafe intent >
  mixed unsafe > unsupported capability > unverified tool > side-effect
  violation > network violation > approval requirement > unhealthy
  dependency > confidence/ambiguity > rollout policy > ALLOW.
- Effective risk = max(intent_risk, tool_risk, policy_risk) — never min.
- A capability descriptor can NEVER lower the risk reported by intent
  classification (§25); intent safety cannot be downgraded by tool
  metadata (§26).
- DENY route exists but NEVER fires in 1.3.0: every failure fails
  closed to LEGACY (byte-compatible with the 1.2.4 behavior). The
  §22 deny-list capabilities (WRITE/DELETE/SYSTEM_CONTROL/...) are
  documented only — they are not resolvable and have no execution
  implementation.
- Feature flag HERMES_CAPABILITY_ROUTER_V2 (off | shadow | enforce),
  default off, unknown → off. Shadow compares legacy vs capability
  decisions without changing routes; enforce routes through this
  layer for the exact 1.2.4 scope.
"""

from .capabilities import (
    AccessMode,
    ApprovalPolicy,
    Capability,
    CapabilityRoute,
    HealthRequirement,
    HealthState,
    NetworkPolicy,
    PolicyVerdict,
    RiskClass,
)
from .flags import (
    CAPABILITY_ROUTER_MODES,
    ROLLOUT_MODES,
    parse_capability_router_mode,
    parse_rollout_mode,
    read_capability_router_flags,
)
from .metrics import CapabilityRouterStats
from .models import (
    CapabilityDescriptor,
    CapabilityRequirement,
    CapabilityRouteDecision,
    PolicyDecision,
    PolicyReason,
    ReasonCode,
    ResolvedCapability,
)
from .policy import (
    CapabilityPolicyEngine,
    DEFAULT_HEALTH_TTL,
    POLICY_VERSION,
    PolicyContext,
    normalize_health_snapshot,
)
from .registry import CapabilityRegistry, RegistryValidationError
from .resolver import CapabilityResolver
from .router import CapabilityRouter, legacy_reason_for

CAPABILITY_ROUTER_VERSION = "capability-router-v1"

__all__ = [
    "Capability",
    "CapabilityRoute",
    "RiskClass",
    "AccessMode",
    "NetworkPolicy",
    "ApprovalPolicy",
    "PolicyVerdict",
    "HealthRequirement",
    "HealthState",
    "ReasonCode",
    "PolicyReason",
    "CapabilityRequirement",
    "CapabilityDescriptor",
    "ResolvedCapability",
    "CapabilityRouteDecision",
    "PolicyDecision",
    "CapabilityRegistry",
    "RegistryValidationError",
    "CapabilityResolver",
    "CapabilityPolicyEngine",
    "PolicyContext",
    "CapabilityRouter",
    "legacy_reason_for",
    "CapabilityRouterStats",
    "parse_capability_router_mode",
    "parse_rollout_mode",
    "read_capability_router_flags",
    "CAPABILITY_ROUTER_MODES",
    "ROLLOUT_MODES",
    "CAPABILITY_ROUTER_VERSION",
    "POLICY_VERSION",
    "DEFAULT_HEALTH_TTL",
    "normalize_health_snapshot",
]
