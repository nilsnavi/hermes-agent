"""Capability Registry (Sprint 1.3.0 §4, §6, §27).

Static, explicit registry of verified capability descriptors. There is
NO dynamic arbitrary tool discovery — every routable tool must be
declared here AND validated against the verified legacy metadata
contracts (Sprint 1.2.1 §5 / 1.2.2 §3-§5) at construction time.

Single source of truth (§6): tool safety metadata (side_effect /
idempotent / network / approval) is NOT duplicated in this layer — the
descriptors are validated against, and must agree with, the existing
verified metadata tables (``STATUS_TOOL_METADATA`` /
``SEARCH_TOOL_METADATA`` in agent.intent_router.enforcement). A drift
between the registry and the verified contracts fails validation
(§27): duplicate capabilities → error, duplicate production tool
mapping → error, unverified routed capability → error, READ_ONLY
capability mapped to a write tool → error, network-forbidden
capability mapped to a network tool → error.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from agent.intent_router.enforcement import (
    SEARCH_TOOL_METADATA,
    STATUS_TOOL_METADATA,
    VERIFIED_SEARCH_TOOLS,
    VERIFIED_STATUS_READ_TOOLS,
)

from .capabilities import (
    Capability,
    HealthRequirement,
    RiskClass,
)
from .models import CapabilityDescriptor


class RegistryValidationError(Exception):
    """Registry construction failed a §27 invariant."""


@dataclass(frozen=True)
class RegistryEntry:
    capability: Capability
    tool_name: str
    verified: bool
    side_effect: str
    idempotent: bool
    network: bool
    approval_required: bool
    timeout: float
    health_dependency: str
    health_requirement: HealthRequirement = HealthRequirement.HEALTHY

    def to_dict(self) -> Dict[str, object]:
        return {
            "capability": self.capability.value,
            "tool_name": self.tool_name,
            "verified": self.verified,
            "side_effect": self.side_effect,
            "idempotent": self.idempotent,
            "network": self.network,
            "approval_required": self.approval_required,
            "timeout": self.timeout,
            "health_dependency": self.health_dependency,
            "health_requirement": self.health_requirement.value,
        }


#: §4/§5 — static descriptor table. The facts (side_effect, idempotent,
#: network, approval) MUST match the verified legacy contracts — the
#: constructor cross-validates and raises on any drift.
DEFAULT_DESCRIPTORS: List[CapabilityDescriptor] = [
    CapabilityDescriptor(
        capability=Capability.STATUS_RUNTIME,
        tool_name="runtime_status",
        health_dependency="gateway",
    ),
    CapabilityDescriptor(
        capability=Capability.STATUS_GATEWAY,
        tool_name="gateway_status",
        health_dependency="gateway",
    ),
    CapabilityDescriptor(
        capability=Capability.STATUS_INTEGRATION,
        tool_name="integration_status",
        health_dependency="gateway",
    ),
    CapabilityDescriptor(
        capability=Capability.STATUS_SCHEDULER,
        tool_name="scheduler_status",
        health_dependency="gateway",
    ),
    CapabilityDescriptor(
        capability=Capability.STATUS_PROVIDER,
        tool_name="provider_status",
        health_dependency="gateway",
    ),
    CapabilityDescriptor(
        capability=Capability.OPERATIONAL_SEARCH,
        tool_name="operational_log_search",
        health_dependency="search_source",
    ),
]

#: Canonical legacy metadata contract per tool (single source of truth).
_TOOL_METADATA: Dict[str, Dict[str, object]] = {
    **STATUS_TOOL_METADATA,
    **SEARCH_TOOL_METADATA,
}


def _tool_contract(tool: str) -> Optional[Dict[str, object]]:
    return _TOOL_METADATA.get(tool)


class CapabilityRegistry:
    """Static verified capability registry (§4).

    Construction validates the full table (§27); any violation raises
    :class:`RegistryValidationError` BEFORE anything can route.
    """

    def __init__(
        self,
        descriptors: Optional[Iterable[CapabilityDescriptor]] = None,
        validate: bool = True,
    ) -> None:
        self._entries: Dict[Capability, RegistryEntry] = {}
        self._by_tool: Dict[str, Capability] = {}
        source = list(descriptors) if descriptors is not None \
            else list(DEFAULT_DESCRIPTORS)
        for d in source:
            self._add(d)
        if validate:
            self.validate()

    def _add(self, d: CapabilityDescriptor) -> None:
        if d.capability in self._entries:
            raise RegistryValidationError(
                f"duplicate capability {d.capability.value}")
        if d.tool_name in self._by_tool:
            raise RegistryValidationError(
                f"duplicate production tool mapping "
                f"{d.tool_name} → {d.capability.value}")
        if not d.verified:
            raise RegistryValidationError(
                f"unverified routed capability {d.capability.value}")
        self._entries[d.capability] = RegistryEntry(
            capability=d.capability,
            tool_name=d.tool_name,
            verified=d.verified,
            side_effect=d.side_effect,
            idempotent=d.idempotent,
            network=d.network,
            approval_required=d.approval_required,
            timeout=d.timeout,
            health_dependency=d.health_dependency,
            health_requirement=getattr(
                d, "health_requirement", HealthRequirement.HEALTHY),
        )
        self._by_tool[d.tool_name] = d.capability

    # ── §27 validation ───────────────────────────────────────────

    def validate(self) -> None:
        """Cross-validate every descriptor against the verified legacy
        tool contracts. Raises :class:`RegistryValidationError` on any
        §27 violation (risk mismatch, network violation, unknown tool,
        contract drift)."""
        for cap, entry in self._entries.items():
            contract = _tool_contract(entry.tool_name)
            if contract is None:
                raise RegistryValidationError(
                    f"capability {cap.value} tool {entry.tool_name} "
                    f"has no verified legacy contract")
            contract_side = str(contract.get("side_effect") or "UNKNOWN")
            contract_network = bool(contract.get("network"))
            # The descriptor must not LOWER the risk of the verified
            # contract (§25: a descriptor can never understate risk) —
            # READ_ONLY contract + riskier descriptor → error; a
            # WRITE-contract tool can never back a READ_ONLY capability.
            if contract_side == "READ_ONLY" and \
                    entry.side_effect != RiskClass.READ_ONLY.value:
                raise RegistryValidationError(
                    f"risk mismatch: capability {cap.value} declares "
                    f"{entry.side_effect} but the verified contract of "
                    f"tool {entry.tool_name} is READ_ONLY (§25)")
            if entry.side_effect == RiskClass.READ_ONLY.value and \
                    contract_side != "READ_ONLY":
                raise RegistryValidationError(
                    f"risk mismatch: {cap.value} declares READ_ONLY but "
                    f"tool {entry.tool_name} is {contract_side}")
            if contract_side == "READ_ONLY" and \
                    not bool(contract.get("idempotent")):
                raise RegistryValidationError(
                    f"tool {entry.tool_name} READ_ONLY but not idempotent")
            # Network-forbidden capability mapped to a network tool.
            if not entry.network and contract_network:
                raise RegistryValidationError(
                    f"network violation: {cap.value} forbids network "
                    f"but tool {entry.tool_name} uses it")
            if entry.network and not contract_network:
                # Descriptor claims network where the verified contract
                # is local — the descriptor cannot widen the surface.
                raise RegistryValidationError(
                    f"network violation: {cap.value} declares network "
                    f"but the verified contract of tool "
                    f"{entry.tool_name} is local")

    # ── lookups ──────────────────────────────────────────────────

    def lookup(self, capability: Capability) -> Optional[RegistryEntry]:
        return self._entries.get(capability)

    def entry_for_tool(self, tool_name: str) -> Optional[RegistryEntry]:
        """RegistryEntry for a tool name, or None if not registered.

        Added for Sprint 1.3.2 (verified tool executor registry
        binding) — additive lookup, no behavior change.
        """
        capability = self._by_tool.get(tool_name)
        if capability is None:
            return None
        return self._entries.get(capability)

    def tool_for(self, capability: Capability) -> Optional[str]:
        entry = self._entries.get(capability)
        return entry.tool_name if entry else None

    def has(self, capability: Capability) -> bool:
        return capability in self._entries

    def names(self) -> List[str]:
        return sorted(c.value for c in self._entries)

    def tools(self) -> List[str]:
        return sorted(self._by_tool)

    def summary(self) -> Dict[str, object]:
        return {
            "capabilities": self.names(),
            "tools": self.tools(),
            "entries": {
                k.value: v.to_dict() for k, v in
                sorted(self._entries.items(), key=lambda kv: kv[0].value)
            },
        }

    # ── tool verification helpers (used by the policy engine) ────

    def tool_verified(self, tool: str) -> bool:
        """Tool is registered AND carries the READ_ONLY + idempotent +
        no-network contract (Sprint 1.2.1 §5 / 1.2.2 §3)."""
        contract = _tool_contract(tool)
        if contract is None:
            return False
        return (
            contract.get("side_effect") == "READ_ONLY"
            and bool(contract.get("idempotent"))
            and not bool(contract.get("network"))
        )

    def tool_metadata(self, tool: str) -> Optional[Dict[str, object]]:
        return _tool_contract(tool)


__all__ = [
    "CapabilityRegistry",
    "RegistryValidationError",
    "RegistryEntry",
    "DEFAULT_DESCRIPTORS",
]
