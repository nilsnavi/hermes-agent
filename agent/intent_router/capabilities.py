"""Capability registry (Sprint 1.1 §22-25).

A CAPABILITY is a named, verified ability of the V2 execution surface —
NOT a tool. ``CapabilityRegistry`` maps intent requirements to the
current V2 capability surface and answers "can V2 satisfy this?"

Only PRODUCTION-SAFE, verified capabilities are registered. We never
claim WRITE / DELETE / SYSTEM_CONTROL while they don't exist.

Intent → required capabilities mapping:

- STATUS_READ / INFORMATION_READ / DIAGNOSTIC → READ_RUNTIME_STATUS
  (runtime_status, canary_ping are the current read-only surface)
- SEARCH_READ / ANALYSIS / SUMMARIZATION / CODE_ASSIST / PLANNING →
  no verified V2 capability yet → capability missing → LEGACY.
- WRITE / DELETE / SYSTEM / SCHEDULE / APPROVAL → explicitly NOT
  satisfiable by the canary surface (write surface absent).
"""

from typing import Dict, Iterable, List, Optional, Set

from .exceptions import CapabilityUnknownError
from .models import IntentType

#: Verified production-safe V2 capabilities (Sprint 1.1 §24).
VERIFIED_V2_CAPABILITIES: Dict[str, str] = {
    "READ_RUNTIME_STATUS": "read the runtime/gateway status locally "
                           "(runtime_status, canary_ping; READ_ONLY)",
}

#: Intent → required capability names.
INTENT_CAPABILITIES: Dict[IntentType, List[str]] = {
    IntentType.STATUS_READ: ["READ_RUNTIME_STATUS"],
    IntentType.INFORMATION_READ: ["READ_RUNTIME_STATUS"],
    IntentType.DIAGNOSTIC: ["READ_RUNTIME_STATUS"],
    # read-leaning intents with NO verified V2 surface → empty means
    # "not satisfiable" (capability missing → LEGACY).
    IntentType.SEARCH_READ: [],
    IntentType.ANALYSIS: [],
    IntentType.SUMMARIZATION: [],
    IntentType.CODE_ASSIST: [],
    IntentType.PLANNING: [],
    IntentType.CONVERSATION: [],
    # unsafe families: never satisfiable by the canary surface.
    IntentType.WRITE_ACTION: [],
    IntentType.DELETE_ACTION: [],
    IntentType.SYSTEM_ACTION: [],
    IntentType.SCHEDULE_ACTION: [],
    IntentType.APPROVAL_ACTION: [],
    IntentType.UNKNOWN: [],
}


class CapabilityRegistry:
    """Registry of declared capabilities + current V2 surface."""

    def __init__(self, capabilities: Optional[Dict[str, str]] = None) -> None:
        self._capabilities: Dict[str, str] = dict(
            capabilities or VERIFIED_V2_CAPABILITIES
        )

    def has(self, capability: str) -> bool:
        return capability in self._capabilities

    def names(self) -> List[str]:
        return sorted(self._capabilities)

    def describe(self, capability: str) -> Optional[str]:
        return self._capabilities.get(capability)

    def register(self, capability: str, description: str) -> None:
        """Declare a NEW capability (tests / future verified surface)."""
        self._capabilities[capability] = description

    # ── intent → capability matching (§23) ──────────────────────────

    def required_for(self, intent: IntentType) -> List[str]:
        return list(INTENT_CAPABILITIES.get(intent, []))

    def capabilities_satisfied(
        self, required: Iterable[str]
    ) -> bool:
        """All required capabilities exist in the registry.

        An intent with an EMPTY requirement list is NOT satisfied:
        empty means "no verified V2 surface" → capability missing →
        LEGACY. Callers wanting a trivial match must check explicitly.
        """
        reqs = list(required)
        if not reqs:
            return False
        return all(r in self._capabilities for r in reqs)

    def capability_gap(
        self, required: Iterable[str]
    ) -> List[str]:
        reqs = list(required)
        return [r for r in reqs if r not in self._capabilities]

    def tools_for_capability(self, capability: str) -> List[str]:
        """Tools that provide a capability (canary registry, verified)."""
        mapping = {
            "READ_RUNTIME_STATUS": ["runtime_status", "canary_ping"],
        }
        if capability not in mapping:
            raise CapabilityUnknownError(capability)
        return list(mapping[capability])


__all__ = [
    "CapabilityRegistry",
    "VERIFIED_V2_CAPABILITIES",
    "INTENT_CAPABILITIES",
]
