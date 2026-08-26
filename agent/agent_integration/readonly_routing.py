"""Read-only routing (Phase 6 §11, §23, §24).

``ReadOnlyRouter`` selects an agent to run an admitted read-only step, choosing
ONLY among: the runtime-owned (sealed) registry, ENABLED agents, agents whose
health/admission verdict is ADMISSIBLE (Phase 5 ``admission_status``), and
agents that declaratively offer the required read-only capability. An UNKNOWN
or not-admissible agent is EXCLUDED. The router NEVER executes, dispatches to
tools, or grants permissions; it only returns an agent id. The failed-agent
exclusion (ORCH-003) is applied to the candidate set before selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Callable, Protocol

from agent.agent_runtime.registry import AgentRegistry
from agent.agent_system.health import AgentAdmissionStatus

from .capabilities import ReadOnlyCapability
from .supervisor_state import exclude_failed

_MISSING_DECLARATION = "this agent offers no read-only capability"


class NoReadOnlyRoute(ValueError):
    """Raised when no admissible/enabled agent matches the capability."""


class SealedRegistry(Protocol):
    """Runtime-owned, sealed registry view (satisfied by SystemAgentRuntime).

    ``registry()`` exposes the immutable AgentRegistry (``.list()``); the seal
    and digest methods detect a rebound/mutated registry as REGISTRY_DRIFT.
    """

    def registry(self) -> AgentRegistry: ...

    def assert_registry_sealed(self) -> str: ...

    def registry_digest(self) -> str: ...


# Declarative map: which system agents may offer which read-only capability.
# This is METADATA (never a grant); the boundary admission still certifies the
# actual read-only execution. Mapping uses the Phase 4/5 system agent ids.
READONLY_AGENT_CAPABILITIES: "dict[str, frozenset[ReadOnlyCapability]]" = {
    "monitoring": frozenset({ReadOnlyCapability.READ_HEALTH, ReadOnlyCapability.READ_STATUS}),
    "research": frozenset({ReadOnlyCapability.READ_TEXT_RESOURCE, ReadOnlyCapability.READ_FILE_METADATA}),
    "coding": frozenset({ReadOnlyCapability.SEARCH_INDEX, ReadOnlyCapability.READ_FILE_METADATA}),
    "reviewer": frozenset({ReadOnlyCapability.READ_AUDIT_SUMMARY, ReadOnlyCapability.READ_CONFIGURATION_SUMMARY}),
    "memory": frozenset({ReadOnlyCapability.READ_MEMORY_CONTEXT}),
}


@dataclass(frozen=True, slots=True)
class ReadOnlyRoute:
    agent_id: str
    version: int
    capability: ReadOnlyCapability


class ReadOnlyRouter:
    """Deterministic read-only agent selection (no dispatch/execute/grant)."""

    __slots__ = ("_sealed_registry", "_admission", "_enabled")

    def __init__(
        self,
        *,
        sealed_registry: SealedRegistry,
        admission: Callable[[str], tuple[AgentAdmissionStatus, str]],
        enabled: AbstractSet[str],
    ) -> None:
        if not isinstance(enabled, (frozenset, set)):
            raise ValueError("enabled must be a set-like collection of agent ids")
        self._sealed_registry = sealed_registry
        self._admission = admission
        self._enabled = frozenset(enabled)

    def route(
        self,
        *,
        required_capability: ReadOnlyCapability,
        exclude: AbstractSet[str] = frozenset(),
    ) -> ReadOnlyRoute | None:
        """Return the best admissible route, or None if none qualifies.

        Unknown health / not-admissible / disabled / non-declaring / excluded
        candidates are never returned.
        """
        if type(required_capability) is not ReadOnlyCapability:
            raise NoReadOnlyRoute("required_capability must be an exact ReadOnlyCapability value")
        for agent_id in exclude:
            if not isinstance(agent_id, str) or not agent_id.strip():
                raise NoReadOnlyRoute("exclude must contain non-empty agent ids")

        definitions = self._sealed_registry.registry().list()  # runtime-owned, sealed registry
        candidates: list[tuple[str, int]] = []
        for definition in sorted(definitions, key=lambda d: d.agent_id):
            agent_id = definition.agent_id
            if agent_id not in self._enabled:
                continue
            if agent_id in exclude:
                continue
            offered = READONLY_AGENT_CAPABILITIES.get(agent_id)
            if not offered or required_capability not in offered:
                continue
            # Phase 5 admission_status: must be ADMISSIBLE (unknown => excluded).
            status, _reason = self._admission(agent_id)
            if status is not AgentAdmissionStatus.ADMISSIBLE:
                continue
            candidates.append((agent_id, definition.version))

        if not candidates:
            return None
        # Deterministic: lexicographically smallest agent_id wins.
        agent_id, version = min(candidates)
        return ReadOnlyRoute(agent_id=agent_id, version=version, capability=required_capability)

    def route_with_failed_exclusion(
        self,
        *,
        required_capability: ReadOnlyCapability,
        failed_agent_id: str,
        alternatives: AbstractSet[str],
    ) -> ReadOnlyRoute | None:
        """ORCH-003-safe alternative routing (failed agent never re-selected).

        The failed agent is put into the EXCLUDE set, so it can never be the
        candidate; routing then picks any OTHER enabled/admissible/declaring
        agent for the required read-only capability.
        """
        exclude_failed(alternatives, failed_agent_id)  # validated exclude set
        return self.route(required_capability=required_capability,
                          exclude=frozenset({failed_agent_id}))


__all__ = [
    "NoReadOnlyRoute",
    "READONLY_AGENT_CAPABILITIES",
    "ReadOnlyRoute",
    "ReadOnlyRouter",
]