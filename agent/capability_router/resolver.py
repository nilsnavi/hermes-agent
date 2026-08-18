"""Capability Resolver (Sprint 1.3.0 §7).

``CapabilityResolver.resolve(intent, subtype)`` maps an intent decision
(intent + deterministic subtype) to a :class:`CapabilityRequirement`
(§3) — or returns ``None`` (NO_CAPABILITY) when the V2 surface cannot
satisfy the request.

Hard invariants (§7):

- DETERMINISTIC: same input → same output, always.
- No LLM. No network. No DB dependency.
- Only the exact Sprint 1.2.4 production authority resolves: STATUS_READ
  (per-subtype verified surface) and SEARCH_READ (limited production
  allowlist scope). EVERYTHING else — INFORMATION_READ, DIAGNOSTIC,
  ANALYSIS, unsafe families, UNKNOWN — resolves to NO_CAPABILITY →
  LEGACY (§11: no production expansion).

Subtype → tool mapping mirrors the verified Sprint 1.2.1 §4 contract
(``STATUS_SUBTYPE_TOOLS``) so tool selection is byte-identical to the
legacy path. HEALTH/SERVICE/GENERIC subtypes sit under STATUS_RUNTIME
(the brief's six-capability surface); their per-request tool still
honors the legacy subtype contract (health_status for HEALTH_STATUS,
runtime_status otherwise).
"""

from typing import Dict, Optional, Tuple

from agent.intent_router.enforcement import (
    STATUS_SUBTYPE_TOOLS,
)

from .capabilities import (
    AccessMode,
    ApprovalPolicy,
    Capability,
    NetworkPolicy,
)
from .models import CapabilityRequirement, ResolvedCapability

#: Read-only requirement template (§3 examples) — every verified
#: capability in 1.3.0 needs exactly this.
_READ_ONLY_REQUIREMENT = dict(
    access_mode=AccessMode.READ_ONLY,
    side_effect="NONE",
    idempotency_required=True,
    network_policy=NetworkPolicy.LOCAL_ONLY,
    approval_policy=ApprovalPolicy.NONE,
    max_tool_calls=1,
)


def _requirement(capability: Capability) -> CapabilityRequirement:
    return CapabilityRequirement(capability=capability,
                                 **_READ_ONLY_REQUIREMENT)


#: STATUS_READ subtype → capability (brief §2 six-capability surface).
STATUS_SUBTYPE_CAPABILITY: Dict[str, Capability] = {
    "service_status": Capability.STATUS_RUNTIME,
    "gateway_status": Capability.STATUS_GATEWAY,
    "runtime_status": Capability.STATUS_RUNTIME,
    "health_status": Capability.STATUS_RUNTIME,
    "integration_status": Capability.STATUS_INTEGRATION,
    "scheduler_status": Capability.STATUS_SCHEDULER,
    "provider_status": Capability.STATUS_PROVIDER,
    "generic": Capability.STATUS_RUNTIME,
}

#: STATUS_READ subtype → per-request tool (Sprint 1.2.1 §4 contract).
#: The primary tool per subtype; canary_ping remains a legacy fallback
#: surface and is NOT a routed tool in 1.3.0 (§5 "if still needed").
STATUS_SUBTYPE_TOOL: Dict[str, str] = {
    subtype: tools[0]
    for subtype, tools in STATUS_SUBTYPE_TOOLS.items()
}

#: SEARCH_READ → the single verified search tool.
SEARCH_TOOL = "operational_log_search"

#: Intents that are NEVER routable (unsafe + off-scope read intents).
#: Unsafe families resolve to NO_CAPABILITY and the legacy pipeline
#: keeps its own guards (§22 document-only deny list).
_NON_ROUTABLE_INTENTS = frozenset({
    "conversation", "summarization", "information_read", "analysis",
    "planning", "code_assist", "diagnostic", "approval_action",
    "write_action", "delete_action", "system_action",
    "schedule_action", "unknown",
})


class CapabilityResolver:
    """Deterministic intent → capability requirement resolver (§7)."""

    VERSION = "capability-resolver-v1"

    def __init__(self) -> None:
        self._requirement_cache: Dict[Tuple[str, Optional[str]],
                                      Optional[ResolvedCapability]] = {}

    def resolve(
        self,
        intent: str,
        subtype: Optional[str] = None,
    ) -> Optional[ResolvedCapability]:
        """Return the capability requirement (+ verified tool) for an
        intent decision, or ``None`` (NO_CAPABILITY → LEGACY).

        ``intent`` is the IntentType VALUE (e.g. ``"status_read"``);
        ``subtype`` is the deterministic StatusSubtype / SearchSubtype
        value (e.g. ``"gateway_status"``).
        """
        key = (str(intent), subtype)
        if key in self._requirement_cache:
            return self._requirement_cache[key]
        result = self._resolve_uncached(intent, subtype)
        self._requirement_cache[key] = result
        return result

    def _resolve_uncached(
        self, intent: str, subtype: Optional[str],
    ) -> Optional[ResolvedCapability]:
        if intent == "status_read":
            cap = STATUS_SUBTYPE_CAPABILITY.get(subtype or "generic")
            if cap is None:
                return None
            tool = STATUS_SUBTYPE_TOOL.get(subtype) or "runtime_status"
            return ResolvedCapability(
                requirement=_requirement(cap), tool=tool)
        if intent == "search_read":
            return ResolvedCapability(
                requirement=_requirement(Capability.OPERATIONAL_SEARCH),
                tool=SEARCH_TOOL)
        return None

    def supported_intents(self) -> Tuple[str, ...]:
        return ("status_read", "search_read")


__all__ = [
    "CapabilityResolver",
    "STATUS_SUBTYPE_CAPABILITY",
    "STATUS_SUBTYPE_TOOL",
    "SEARCH_TOOL",
]
