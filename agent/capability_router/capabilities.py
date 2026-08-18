"""Capability model (Sprint 1.3.0 §2, §22-25).

A CAPABILITY is a named, VERIFIED ability of the V2 execution surface —
NOT a tool. Capabilities are the bridge between intent (STATUS_READ /
SEARCH_READ) and the verified tool registry.

Initial verified capabilities (§2) — exactly the six production-safe
surface entries. No capability beyond this set is routable in 1.3.0:

    STATUS_RUNTIME        runtime_status
    STATUS_GATEWAY        gateway_status
    STATUS_INTEGRATION    integration_status
    STATUS_SCHEDULER      scheduler_status
    STATUS_PROVIDER       provider_status
    OPERATIONAL_SEARCH    operational_log_search

Deny list (§22) — explicitly NON-routable for V2, DOCUMENTED ONLY, no
execution implementation: WRITE, DELETE, SYSTEM_CONTROL,
SCHEDULE_MUTATION, APPROVAL_WRITE, FILESYSTEM_SEARCH, WEB_SEARCH,
SECRET_ACCESS, ARBITRARY_DB, UNKNOWN.

Future placeholders (§23) — MAY be documented but are verified=false /
routable=false, never registered, never activated: MESSAGE_SEND,
REMINDER_CREATE, FILE_READ, WEB_SEARCH, WORKFLOW_EXECUTION.
"""

from enum import Enum
from typing import Dict, Tuple

# ══════════════════════════════════════════════════════════════════
# §2 — capability enum
# ══════════════════════════════════════════════════════════════════


class Capability(Enum):
    """The initial verified V2 capability surface (§2)."""

    STATUS_RUNTIME = "STATUS_RUNTIME"
    STATUS_GATEWAY = "STATUS_GATEWAY"
    STATUS_INTEGRATION = "STATUS_INTEGRATION"
    STATUS_SCHEDULER = "STATUS_SCHEDULER"
    STATUS_PROVIDER = "STATUS_PROVIDER"
    OPERATIONAL_SEARCH = "OPERATIONAL_SEARCH"


#: All six verified capabilities (registry surface — §32 tests).
VERIFIED_CAPABILITIES: Tuple[Capability, ...] = tuple(Capability)

#: Canonical tool for each capability (§4/§5 descriptor.tool_name).
#: The per-request tool can be more specific via the subtype contract
#: (resolver), but the canonical tool is the registry fact.
CANONICAL_TOOL_BY_CAPABILITY: Dict[Capability, str] = {
    Capability.STATUS_RUNTIME: "runtime_status",
    Capability.STATUS_GATEWAY: "gateway_status",
    Capability.STATUS_INTEGRATION: "integration_status",
    Capability.STATUS_SCHEDULER: "scheduler_status",
    Capability.STATUS_PROVIDER: "provider_status",
    Capability.OPERATIONAL_SEARCH: "operational_log_search",
}

#: §22 — deny-list capabilities. DOCUMENT ONLY. Never resolvable,
#: never registered, no execution implementation.
DENY_LIST_CAPABILITIES: Tuple[str, ...] = (
    "WRITE",
    "DELETE",
    "SYSTEM_CONTROL",
    "SCHEDULE_MUTATION",
    "APPROVAL_WRITE",
    "FILESYSTEM_SEARCH",
    "WEB_SEARCH",
    "SECRET_ACCESS",
    "ARBITRARY_DB",
    "UNKNOWN",
)

#: §23 — future placeholders. verified=false, routable=false, never
#: registered in 1.3.0.
FUTURE_PLACEHOLDER_CAPABILITIES: Tuple[str, ...] = (
    "MESSAGE_SEND",
    "REMINDER_CREATE",
    "FILE_READ",
    "WEB_SEARCH",
    "WORKFLOW_EXECUTION",
)


# ══════════════════════════════════════════════════════════════════
# §24 — risk classes
# ══════════════════════════════════════════════════════════════════


class RiskClass(Enum):
    """Normalized risk classes (§24 / Sprint 1.3.1 §5).

    Current production V2 surface is READ_ONLY only. The order below
    is the escalation order used by ``RISK_ORDER`` for the §25
    effective-risk rule (max of intent/tool/policy risk — never min).
    Sprint 1.3.1 §5: risk classes are canonical — READ_ONLY,
    REVERSIBLE_WRITE, IRREVERSIBLE_WRITE, SYSTEM_CONTROL,
    SECRET_ACCESS, UNKNOWN.
    """

    READ_ONLY = "READ_ONLY"
    REVERSIBLE_WRITE = "REVERSIBLE_WRITE"
    IRREVERSIBLE_WRITE = "IRREVERSIBLE_WRITE"
    SYSTEM_CONTROL = "SYSTEM_CONTROL"
    SECRET_ACCESS = "SECRET_ACCESS"
    UNKNOWN = "UNKNOWN"


class HealthRequirement(Enum):
    """Sprint 1.3.1 §6 — what a capability descriptor requires from
    the dependency health snapshot.

    - HEALTHY: only a healthy dependency passes. Unknown/unavailable
      health fails closed (production read capabilities use this).
    - DEGRADED_ALLOWED: healthy or degraded passes (reserved).
    - NO_HEALTH_REQUIREMENT: the gate is skipped (reserved).
    """

    HEALTHY = "HEALTHY"
    DEGRADED_ALLOWED = "DEGRADED_ALLOWED"
    NO_HEALTH_REQUIREMENT = "NO_HEALTH_REQUIREMENT"


class HealthState(Enum):
    """Sprint 1.3.1 §6/§7 — normalized health state of a dependency.

    UNKNOWN covers both "no snapshot" and "snapshot expired beyond the
    bounded TTL" (§7 — expired health is UNKNOWN, never stale-ok).
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"



#: Escalation order (UNKNOWN is the most dangerous — fail closed).
RISK_ORDER: Dict[RiskClass, int] = {
    RiskClass.READ_ONLY: 0,
    RiskClass.REVERSIBLE_WRITE: 1,
    RiskClass.IRREVERSIBLE_WRITE: 2,
    RiskClass.SYSTEM_CONTROL: 3,
    RiskClass.SECRET_ACCESS: 4,
    RiskClass.UNKNOWN: 5,
}


def max_risk(*risks: RiskClass) -> RiskClass:
    """§25 — effective risk = max(intent, tool, policy). Never minimum.

    Unknown metadata fails closed to the UNKNOWN (most dangerous)
    class instead of being treated as safe.
    """
    if not risks:
        return RiskClass.UNKNOWN
    return max(risks, key=lambda r: RISK_ORDER.get(r, RISK_ORDER[RiskClass.UNKNOWN]))


#: ExpectedSideEffect (classifier) → RiskClass (capability model).
#: Compatible mapping so the intent side-effect expectation can feed
#: the §25 max() rule without inventing a second vocabulary.
EXPECTED_SIDE_EFFECT_TO_RISK: Dict[str, RiskClass] = {
    "none": RiskClass.READ_ONLY,
    "read_only": RiskClass.READ_ONLY,
    "reversible_write": RiskClass.REVERSIBLE_WRITE,
    "irreversible_write": RiskClass.IRREVERSIBLE_WRITE,
    "system_change": RiskClass.SYSTEM_CONTROL,
    "unknown": RiskClass.UNKNOWN,
}


# ══════════════════════════════════════════════════════════════════
# §3/§4 — policy vocabulary
# ══════════════════════════════════════════════════════════════════


class AccessMode(Enum):
    READ_ONLY = "READ_ONLY"
    WRITE = "WRITE"


class NetworkPolicy(Enum):
    LOCAL_ONLY = "LOCAL_ONLY"
    NETWORK = "NETWORK"


class ApprovalPolicy(Enum):
    NONE = "NONE"
    REQUIRED = "REQUIRED"


class CapabilityRoute(Enum):
    """§10 — route values of a CapabilityRouteDecision."""

    V2 = "V2"
    LEGACY = "LEGACY"
    DENY = "DENY"


class PolicyVerdict(Enum):
    """§8 — CapabilityPolicyEngine verdicts."""

    ALLOW_V2 = "ALLOW_V2"
    LEGACY = "LEGACY"
    DENY = "DENY"


__all__ = [
    "Capability",
    "VERIFIED_CAPABILITIES",
    "CANONICAL_TOOL_BY_CAPABILITY",
    "DENY_LIST_CAPABILITIES",
    "FUTURE_PLACEHOLDER_CAPABILITIES",
    "RiskClass",
    "RISK_ORDER",
    "max_risk",
    "EXPECTED_SIDE_EFFECT_TO_RISK",
    "HealthRequirement",
    "HealthState",
    "AccessMode",
    "NetworkPolicy",
    "ApprovalPolicy",
    "CapabilityRoute",
    "PolicyVerdict",
]
