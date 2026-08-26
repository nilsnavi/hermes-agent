"""Agent health/status model.

A fail-closed health evaluator for the system-agent layer. The cardinal rule:
without positive, fresh evidence an agent is NOT healthy. Absent registry entry,
missed heartbeat, stale heartbeat, or a lifecycle that is not ready all resolve
to an unhealthy status -- never a silent green.

Health reports readiness ONLY. A "healthy" status confers no execution authority
and never implies permission to run anything; health is a routing signal for the
control plane, handled downstream as availability. This module exposes no
grant/authorize/execute/dispatch surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import time as _time
from typing import Callable

from agent.agent_runtime.lifecycle import AgentLifecycleStatus
from agent.agent_runtime.registry import AgentRegistry

from .exceptions import AgentHealthError, UnknownSystemAgent

_Clock = Callable[[], float]


class AgentHealthStatus(Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class AgentAdmissionStatus(Enum):
    """Fail-closed verdict used specifically for EXECUTION ADMISSION.

    Only ``ADMISSIBLE`` may proceed; every other value (including UNKNOWN) must
    be treated as a denial by any admission consumer. This is strictly stricter
    than the read-only diagnostic ``AgentHealthStatus``.
    """

    ADMISSIBLE = "admissible"
    NOT_ADMISSIBLE = "not_admissible"
    UNKNOWN = "unknown"


# A lifecycle is "ready" only when the agent is registered, enabled, and active
# enough to be a routing candidate. Anything terminal or merely registered
# degrades or fails closed.
_READY_LIFECYCLES = frozenset(
    {AgentLifecycleStatus.READY, AgentLifecycleStatus.ACTIVE}
)


@dataclass(frozen=True, slots=True)
class AgentHealthReport:
    """Immutable, bounded health verdict for one system agent."""

    agent_id: str
    status: AgentHealthStatus
    reason: str
    version: int | None = None
    last_observed: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "status": self.status.value,
            "reason": self.reason,
            "version": self.version,
            "last_observed": self.last_observed,
        }


class AgentHealthModel:
    """Fail-closed health evaluation over registry membership + lifecycle + ticks.

    ``observe`` records positive liveness evidence (a heartbeat) for a registered
    agent. ``evaluate`` returns a verdict; the default status is UNKNOWN and every
    missing/stale signal degrades the verdict to UNHEALTHY. This model never
    inspects execution state and never grants the ability to run anything.
    """

    __slots__ = ("_registry", "_lifecycle_status", "_ttl", "_clock", "_last_observed")

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        lifecycle_status: Callable[[str], AgentLifecycleStatus] | None = None,
        ttl: float = 60.0,
        clock: _Clock | None = None,
    ) -> None:
        if type(registry) is not AgentRegistry:
            raise AgentHealthError("registry must be an exact AgentRegistry")
        if (
            isinstance(ttl, bool)
            or not isinstance(ttl, (int, float))
            or ttl <= 0
        ):
            raise AgentHealthError("ttl must be a positive number")
        self._registry = registry
        self._lifecycle_status = lifecycle_status
        self._ttl = float(ttl)
        self._clock = clock if clock is not None else _time
        self._last_observed: dict[str, float] = {}

    def _confirm_registered(self, agent_id: str) -> None:
        try:
            self._registry.latest(agent_id)
        except KeyError as exc:
            raise UnknownSystemAgent(f"agent {agent_id!r} is not registered") from exc

    def observe(self, agent_id: str, *, now: float | None = None) -> AgentHealthReport:
        """Record a positive liveness signal; fail-closed against unknown agents."""
        self._confirm_registered(agent_id)
        timestamp = self._clock() if now is None else now
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise AgentHealthError("now must be a number or None")
        previous = self._last_observed.get(agent_id)
        if previous is not None and timestamp < previous:
            raise AgentHealthError("cannot observe an earlier timestamp (backward clock)")
        self._last_observed[agent_id] = timestamp
        return self.evaluate(agent_id, now=timestamp)

    def evaluate(self, agent_id: str, *, now: float | None = None) -> AgentHealthReport:
        timestamp = self._clock() if now is None else now
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise AgentHealthError("now must be a number or None")

        try:
            first = self._registry.latest(agent_id)
        except KeyError as exc:
            raise UnknownSystemAgent(f"agent {agent_id!r} is not registered") from exc
        version = first.version

        last = self._last_observed.get(agent_id)
        if last is None:
            return AgentHealthReport(
                agent_id=agent_id,
                status=AgentHealthStatus.UNHEALTHY,
                reason="never observed (no positive liveness evidence)",
                version=version,
                last_observed=None,
            )
        if timestamp - last > self._ttl:
            return AgentHealthReport(
                agent_id=agent_id,
                status=AgentHealthStatus.UNHEALTHY,
                reason="stale heartbeat (exceeded TTL)",
                version=version,
                last_observed=last,
            )

        if self._lifecycle_status is not None:
            lifecycle = self._lifecycle_status(agent_id)
            if type(lifecycle) is not AgentLifecycleStatus:
                return AgentHealthReport(
                    agent_id=agent_id,
                    status=AgentHealthStatus.UNHEALTHY,
                    reason="lifecycle provider returned an invalid status",
                    version=version,
                    last_observed=last,
                )
            if lifecycle in _READY_LIFECYCLES:
                status = AgentHealthStatus.HEALTHY
                reason = "registered, live, and lifecycle-ready"
            elif lifecycle is AgentLifecycleStatus.REGISTERED:
                status = AgentHealthStatus.DEGRADED
                reason = "registered and live but not yet lifecycle-ready"
            else:
                status = AgentHealthStatus.UNHEALTHY
                reason = f"lifecycle is {lifecycle.value!r} (not ready)"
        else:
            status = AgentHealthStatus.HEALTHY
            reason = "registered and live"

        return AgentHealthReport(
            agent_id=agent_id,
            status=status,
            reason=reason,
            version=version,
            last_observed=last,
        )

    def admission_status(
        self, agent_id: str, *, now: float | None = None
    ) -> tuple[AgentAdmissionStatus, str]:
        """Strict, fail-closed verdict for EXECUTION ADMISSION.

        Stricter than ``evaluate``: if the lifecycle provider is unavailable, the
        lifecycle is not READY/ACTIVE, or there is no fresh heartbeat, the agent
        is NOT_ADMISSIBLE/UNKNOWN -- never green for admission. This closes the
        Phase 4 robustness gap where a standalone health model (no lifecycle
        provider) could report HEALTHY.
        """
        self._confirm_registered(agent_id)  # raises UnknownSystemAgent
        timestamp = self._clock() if now is None else now
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise AgentHealthError("now must be a number or None")

        if self._lifecycle_status is None:
            return (
                AgentAdmissionStatus.UNKNOWN,
                "lifecycle provider unavailable -> fail-closed for admission",
            )
        lifecycle = self._lifecycle_status(agent_id)
        if lifecycle not in _READY_LIFECYCLES:
            return (
                AgentAdmissionStatus.NOT_ADMISSIBLE,
                f"lifecycle {lifecycle.value!r} is not ready for admission",
            )
        last = self._last_observed.get(agent_id)
        if last is None:
            return (
                AgentAdmissionStatus.NOT_ADMISSIBLE,
                "no positive liveness evidence for admission",
            )
        if timestamp - last > self._ttl:
            return (
                AgentAdmissionStatus.NOT_ADMISSIBLE,
                "stale heartbeat for admission",
            )
        return AgentAdmissionStatus.ADMISSIBLE, "registered, lifecycle-ready, and fresh"


__all__ = [
    "AgentAdmissionStatus",
    "AgentHealthModel",
    "AgentHealthReport",
    "AgentHealthStatus",
]