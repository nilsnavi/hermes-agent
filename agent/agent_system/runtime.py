"""System-agent runtime (control plane).

The runtime owns the durable, in-memory bookkeeping for system agents: it holds a
frozen ``AgentRegistry`` (item: Agent Registry), registers the first system agent
definitions into it, drives each agent's ``AgentLifecycle``, and tracks health via
``AgentHealthModel``. It is CONTROL PLANE ONLY:

  * registration is bookkeeping, not permission -- the registry only ever admits
    the fixed system implementation ids, so registering a system agent here never
    expands any production capability set;
  * lifecycle transitions are state-machine bookkeeping, not execution;
  * health reports readiness, not the right to run anything.

The runtime has NO execute/dispatch/authorize/grant surface and never touches an
execution kernel.
"""

from __future__ import annotations

import hashlib
import json
from time import time as _time
from typing import Callable

from agent.agent_runtime.exceptions import AgentContractError
from agent.agent_runtime.lifecycle import (
    AgentLifecycle,
    AgentLifecycleStatus,
)
from agent.agent_runtime.permissions import AgentPermissions
from agent.agent_runtime.registry import AgentDefinition, AgentRegistry

from .definitions import SYSTEM_IMPLEMENTATION_IDS, build_system_agent_definitions
from .exceptions import UnknownSystemAgent, UnknownImplementation, AgentRegistryDrift
from .health import (
    AgentAdmissionStatus,
    AgentHealthModel,
    AgentHealthReport,
    AgentHealthStatus,
)

_Clock = Callable[[], float]

_PERMISSION_FIELDS = (
    "read_files",
    "write_files",
    "execute_code",
    "network_access",
    "memory_read",
    "memory_write",
    "agent_message_send",
)


def _permissions_exceed(candidate: AgentPermissions, canonical: AgentPermissions) -> bool:
    """True if ``candidate`` grants any permission the canonical one does not."""
    return any(
        getattr(candidate, name) and not getattr(canonical, name)
        for name in _PERMISSION_FIELDS
    )


class SystemAgentRuntime:
    """Control-plane registry + lifecycle + health manager for system agents."""

    __slots__ = (
        "_registry",
        "_lifecycles",
        "_health",
        "_clock",
        "_registry_digest",
    )

    def __init__(
        self,
        *,
        registry: AgentRegistry | None = None,
        health: AgentHealthModel | None = None,
        clock: _Clock | None = None,
    ) -> None:
        self._clock = clock if clock is not None else _time
        if registry is None:
            registry = AgentRegistry(allowed_implementation_ids=SYSTEM_IMPLEMENTATION_IDS)
        if type(registry) is not AgentRegistry:
            raise AgentContractError("registry must be an exact AgentRegistry")
        self._registry = registry
        self._lifecycles: dict[str, AgentLifecycle] = {}
        # Runtime-owned hardening: reject a caller-supplied registry that already
        # holds any non-canonical implementation, and seal a snapshot digest so a
        # rebound/mutated registry is detected as REGISTRY_DRIFT later.
        self._validate_all_implementations()
        self._seal_snapshot()
        self._health = (
            health
            if health is not None
            else AgentHealthModel(
                self._registry,
                lifecycle_status=self._lifecycle_status,
                clock=self._clock,
            )
        )
        if type(self._health) is not AgentHealthModel:
            raise AgentContractError("health must be an exact AgentHealthModel")

    # -- lifecycle bookkeeping (feed into health) -------------------------------

    def _lifecycle_status(self, agent_id: str) -> AgentLifecycleStatus:
        lifecycle = self._lifecycles.get(agent_id)
        if lifecycle is None:
            return AgentLifecycleStatus.REGISTERED
        return lifecycle.status

    # -- registry integration (scope item 1) -----------------------------------

    def register(self, definition: AgentDefinition) -> AgentDefinition:
        """Register one system-agent definition (idempotent, allowlisted)."""
        if type(definition) is not AgentDefinition:
            raise AgentContractError("definition must be an exact AgentDefinition value")
        # Runtime-owned allowlist hardening: even if a caller injected a wider
        # registry, only the fixed system implementation ids may be admitted.
        if definition.implementation_id not in SYSTEM_IMPLEMENTATION_IDS:
            raise UnknownImplementation(
                f"implementation_id {definition.implementation_id!r} is not a system agent implementation"
            )
        self._require_canonical_definition(definition)
        already = self._registry.latest(definition.agent_id) if definition.agent_id in self.registered_ids() else None
        if already is not None and already.version >= definition.version:
            # Idempotent: definition already registered at >= requested version.
            return self._registry.latest(definition.agent_id)
        self._registry.register(definition)
        lifecycle = self._lifecycles.get(definition.agent_id)
        if lifecycle is None or lifecycle.version < definition.version:
            # Lifecycle version tracked in the DEFINITION version domain on a
            # fresh registration, so admission can never silently mismatch a
            # definition version with an older lifecycle counter.
            self._lifecycles[definition.agent_id] = AgentLifecycle(
                status=AgentLifecycleStatus.REGISTERED, version=definition.version
            )
        self._seal_snapshot()
        return self._registry.latest(definition.agent_id)

    def register_system_agents(self) -> tuple[AgentDefinition, ...]:
        """Register all first system-agent definitions into the existing registry."""
        registered = tuple(
            self.register(definition) for definition in build_system_agent_definitions()
        )
        return registered

    def registry(self) -> AgentRegistry:
        """Read access to the underlying immutable-by-contract registry."""
        return self._registry

    def registered_ids(self) -> tuple[str, ...]:
        return tuple(
            definition.agent_id for definition in sorted(self._registry.list(), key=lambda d: d.agent_id)
        )

    # -- lifecycle runtime (scope item 3) --------------------------------------

    def lifecycle(self, agent_id: str) -> AgentLifecycle | None:
        """Return the current lifecycle for a registered agent, or None."""
        self._require_registered(agent_id)
        return self._lifecycles.get(agent_id)

    def transition(
        self, agent_id: str, to_status: AgentLifecycleStatus
    ) -> AgentLifecycle:
        """Drive one legal lifecycle transition for a registered agent."""
        self._require_registered(agent_id)
        if type(to_status) is not AgentLifecycleStatus:
            raise AgentContractError("to_status must be an exact AgentLifecycleStatus")
        current = self._lifecycles.get(agent_id)
        if current is None:
            raise UnknownSystemAgent(f"agent {agent_id!r} has no lifecycle")
        if current.status is to_status:
            # No-op self-transition: idempotent, returns the current state.
            return current
        if not current.can_transition_to(to_status):
            raise AgentContractError(
                f"cannot transition agent {agent_id!r} from {current.status.value} to {to_status.value}"
            )
        updated = current.transition(to_status)
        self._lifecycles[agent_id] = updated
        return updated

    # -- health/status (scope item 5) ------------------------------------------

    def observe(self, agent_id: str) -> AgentHealthReport:
        """Record a positive liveness tick for a registered agent."""
        self._require_registered(agent_id)
        return self._health.observe(agent_id)

    def health(self, agent_id: str) -> AgentHealthReport:
        """Current fail-closed health verdict for a registered agent."""
        self._require_registered(agent_id)
        return self._health.evaluate(agent_id)

    # -- introspection ---------------------------------------------------------

    def snapshot(self) -> tuple[dict[str, object], ...]:
        """Per-agent control-plane status snapshot (no execution data)."""
        snapshots: list[dict[str, object]] = []
        for definition in sorted(self._registry.list(), key=lambda d: d.agent_id):
            lifecycle = self._lifecycles.get(definition.agent_id)
            report = self._health.evaluate(definition.agent_id)
            snapshots.append(
                {
                    "agent_id": definition.agent_id,
                    "version": definition.version,
                    "role": definition.role,
                    "lifecycle_status": (
                        lifecycle.status.value if lifecycle else AgentLifecycleStatus.REGISTERED.value
                    ),
                    "health_status": report.status.value,
                    "health_reason": report.reason,
                }
            )
        return tuple(snapshots)

    # -- execution-admission (strict, fail-closed; Phase 5) ---------------------

    def admission_status(self, agent_id: str) -> tuple[AgentAdmissionStatus, str]:
        """Strict, fail-closed admission verdict (stricter than ``health``)."""
        self._require_registered(agent_id)
        return self._health.admission_status(agent_id)

    # -- runtime-owned registry sealing (Phase 4 backlog item) ------------------

    def _canonical_snapshot(self) -> list[dict[str, object]]:
        entries = []
        for definition in sorted(self._registry.list(), key=lambda d: (d.agent_id, d.version)):
            permissions = definition.permissions
            entries.append(
                {
                    "agent_id": definition.agent_id,
                    "version": definition.version,
                    "implementation_id": definition.implementation_id,
                    "capabilities": sorted(definition.capabilities),
                    "permissions": {
                        name: getattr(permissions, name)
                        for name in (
                            "read_files",
                            "write_files",
                            "execute_code",
                            "network_access",
                            "memory_read",
                            "memory_write",
                            "agent_message_send",
                        )
                    },
                    "trust_score": definition.trust_score,
                }
            )
        return entries

    def registry_digest(self) -> str:
        """SHA-256 of the canonical, deterministically-ordered registry snapshot."""
        payload = json.dumps(
            self._canonical_snapshot(), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _seal_snapshot(self) -> None:
        self._registry_digest = self.registry_digest()

    def assert_registry_sealed(self) -> str:
        """Recompute and compare the snapshot digest; raise on REGISTRY_DRIFT."""
        current = self.registry_digest()
        if current != self._registry_digest:
            raise AgentRegistryDrift("registry snapshot drifted (rebound or mutated)")
        return current

    def _validate_all_implementations(self) -> None:
        for definition in self._registry.list():
            if definition.implementation_id not in SYSTEM_IMPLEMENTATION_IDS:
                raise UnknownImplementation(
                    f"implementation_id {definition.implementation_id!r} is not a canonical system agent implementation"
                )

    def _require_canonical_definition(self, definition: AgentDefinition) -> None:
        """Enforce declared-but-not-granted and no capability/permission smuggling.

        A definition may not declare capabilities or grant permissions beyond the
        canonical definition for its agent_id, and may never carry mutation
        permissions (write_files/execute_code) -- a declaration is metadata, not a
        grant, and CodingAgent mutation stays DENIED.
        """
        canonical_list = [d for d in build_system_agent_definitions() if d.agent_id == definition.agent_id]
        if not canonical_list:
            raise UnknownImplementation(
                f"agent_id {definition.agent_id!r} is not a canonical system agent"
            )
        canonical = canonical_list[0]
        if set(definition.capabilities) - set(canonical.capabilities):
            raise AgentContractError(
                "definition declares capabilities beyond the canonical system set (not grantable)"
            )
        if definition.permissions.write_files or definition.permissions.execute_code:
            raise AgentContractError(
                "coding agent mutation permissions (write_files/execute_code) are denied"
            )
        if _permissions_exceed(definition.permissions, canonical.permissions):
            raise AgentContractError(
                "definition grants permissions beyond the canonical system definition"
            )

    def _require_registered(self, agent_id: str) -> None:
        try:
            self._registry.latest(agent_id)
        except KeyError as exc:
            raise UnknownSystemAgent(f"agent {agent_id!r} is not registered") from exc


__all__ = ["SystemAgentRuntime"]