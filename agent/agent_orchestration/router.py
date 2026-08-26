"""Agent Router.

The router selects an agent to run a planned step, based on registered agent
definitions and their quality/trust. It only selects: it returns a chosen
agent ID (or raises if none qualifies) and never executes, never grants
authority, and never dispatches work. Hard gates (required capability,
registered+ready state) are evaluated before any deterministic score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet

from agent.agent_runtime.registry import AgentDefinition, AgentRegistry

# scoring weights for the deterministic route score (architectural doc §5).
W_CAPABILITY = 0.35
W_TRUST = 0.20
W_QUALITY = 0.20
W_AVAILABILITY = 0.15
W_COST = 0.10


class NoRoute(ValueError):
    """Raised when no agent qualifies for a step."""


@dataclass(frozen=True, slots=True)
class RouteSelection:
    agent_id: str
    version: int
    score: float


class AgentRouter:
    """Pure agent selection. No execution surface."""

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        active_versions: AbstractSet[int] | None = None,
    ) -> None:
        if type(registry) is not AgentRegistry:
            raise ValueError("registry must be an exact AgentRegistry")
        self._registry = registry
        self._active_versions = frozenset(active_versions) if active_versions is not None else frozenset()

    def _quality(self, agent_id: str) -> float:
        # Phase 1 AgentQualityModel is not wired to a store here; default to a
        # conservative quality score. The router remains deterministic.
        return 0.5

    def route(
        self,
        *,
        required_capability: str,
        availability: AbstractSet[str] = frozenset(),
    ) -> RouteSelection:
        if not isinstance(required_capability, str) or not required_capability.strip():
            raise NoRoute("required_capability must be a non-empty string")
        if isinstance(availability, (str, bytes)):
            raise NoRoute("availability must be a set-like collection")
        active_set = frozenset(availability)

        candidates: list[tuple[float, AgentDefinition]] = []
        for definition in self._registry.list():
            # hard gate: must offer the capability
            if required_capability not in definition.capabilities:
                continue
            # hard gate: if caller constrained availability, agent must be in it
            if active_set and definition.agent_id not in active_set:
                continue
            if self._active_versions and definition.version not in self._active_versions:
                continue
            # hard gate: trust is a routing signal; still require non-zero
            if definition.trust_score <= 0:
                continue
            score = (
                W_CAPABILITY * 1.0  # capability matched
                + W_TRUST * definition.trust_score
                + W_QUALITY * self._quality(definition.agent_id)
                + W_AVAILABILITY * 1.0
                + W_COST * 0.5
            )
            candidates.append((score, definition))

        if not candidates:
            raise NoRoute(
                f"no agent provides capability {required_capability!r}"
            )
        # Deterministic: highest score, tie-break by agent_id.
        candidates.sort(key=lambda pair: (-pair[0], pair[1].agent_id))
        best = candidates[0][1]
        return RouteSelection(agent_id=best.agent_id, version=best.version, score=candidates[0][0])