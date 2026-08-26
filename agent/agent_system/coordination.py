"""System-agent coordination integration.

Binds the system-agent runtime to the Phase 2 orchestration control plane: it
drives the ``CoordinationState`` machine for a task, selects system agents
through ``AgentRouter`` using health as availability, and moves ``AgentMessage``
envelopes between agents through an ``InMemoryMessageBus``.

It is CONTROL PLANE ONLY. None of routing, a coordinated state, or a delivered
message ever executes work or grants authority -- Planner != executor,
Supervisor != executor, AgentMessage is data not a grant, and health is an
availability signal not permission. This module exposes no execute/dispatch/
authorize/grant surface.
"""

from __future__ import annotations

from agent.agent_orchestration.coordination import (
    CoordinationState,
    CoordinationStatus,
    InvalidCoordinationTransition,
)
from agent.agent_orchestration.message_bus import BusError, InMemoryMessageBus
from agent.agent_orchestration.messages import (
    MessageEnvelope,
    MessagePriority,
    MessageType,
)
from agent.agent_orchestration.router import AgentRouter, NoRoute, RouteSelection

from .exceptions import SystemAgentCoordinationError, UnknownSystemAgent
from .health import AgentHealthStatus
from .runtime import SystemAgentRuntime


class SystemAgentCoordination:
    """Coordination, routing and messaging integration for system agents."""

    __slots__ = ("_runtime", "_router", "_bus", "_states")

    def __init__(
        self,
        runtime: SystemAgentRuntime,
        *,
        router: AgentRouter | None = None,
        bus: InMemoryMessageBus | None = None,
        active_versions: set[int] | None = None,
    ) -> None:
        if type(runtime) is not SystemAgentRuntime:
            raise SystemAgentCoordinationError("runtime must be an exact SystemAgentRuntime")
        self._runtime = runtime
        if router is not None and type(router) is not AgentRouter:
            raise SystemAgentCoordinationError("router must be an exact AgentRouter")
        self._router = (
            router
            if router is not None
            else AgentRouter(self._runtime.registry(), active_versions=frozenset(active_versions or set()))
        )
        self._bus = bus if bus is not None else InMemoryMessageBus()
        self._states: dict[str, CoordinationState] = {}

    # -- coordination state machine --------------------------------------------

    def start(self, task_id: str) -> CoordinationState:
        if not isinstance(task_id, str) or not task_id.strip():
            raise SystemAgentCoordinationError("task_id must be a non-empty string")
        if task_id in self._states:
            return self._states[task_id]
        state = CoordinationState()
        self._states[task_id] = state
        return state

    def state(self, task_id: str) -> CoordinationState | None:
        return self._states.get(task_id)

    def advance(self, task_id: str, to_status: CoordinationStatus) -> CoordinationState:
        if type(to_status) is not CoordinationStatus:
            raise SystemAgentCoordinationError("to_status must be an exact CoordinationStatus")
        current = self._states.get(task_id)
        if current is None:
            current = self.start(task_id)
        if current.status is to_status:
            return current
        try:
            updated = current.transition(to_status)
        except InvalidCoordinationTransition as exc:
            raise SystemAgentCoordinationError(str(exc)) from exc
        self._states[task_id] = updated
        return updated

    # -- routing (health -> availability -> AgentRouter) ------------------------

    def availability(self) -> frozenset[str]:
        """Healthy, non-terminal system agents eligible as routing candidates."""
        eligible: list[str] = []
        for agent_id in self._runtime.registered_ids():
            try:
                report = self._runtime.health(agent_id)
            except UnknownSystemAgent:
                continue
            if report.status is AgentHealthStatus.HEALTHY:
                eligible.append(agent_id)
        return frozenset(eligible)

    def route(self, *, required_capability: str) -> RouteSelection:
        """Select a healthy system agent offering the required capability."""
        try:
            return self._router.route(
                required_capability=required_capability,
                availability=self.availability(),
            )
        except NoRoute as exc:
            raise SystemAgentCoordinationError(str(exc)) from exc

    # -- messaging (AgentMessage is data, not authority) -----------------------

    def send(
        self,
        *,
        task_id: str,
        from_agent: str,
        to_agent: str,
        payload: tuple[object, ...] = (),
        message_id: str | None = None,
        idempotency_key: str | None = None,
        message_type: MessageType = MessageType.REQUEST,
    ) -> MessageEnvelope:
        """Deliver a validated AgentMessage envelope (transport only)."""
        self._require_agent(from_agent)
        self._require_agent(to_agent)
        for token_name, value in (("message_id", message_id), ("idempotency_key", idempotency_key)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise SystemAgentCoordinationError(f"{token_name} must be a non-empty string or None")
        resolved_message_id = (
            message_id if message_id is not None else f"m-{from_agent}-{to_agent}-{task_id}"
        )
        resolved_idempotency = (
            idempotency_key if idempotency_key is not None else resolved_message_id
        )
        env = MessageEnvelope(
            message_id=resolved_message_id,
            schema_version=1,
            from_agent=from_agent,
            to_agent=to_agent,
            type=message_type,
            priority=MessagePriority.NORMAL,
            task_id=task_id,
            idempotency_key=resolved_idempotency,
            payload=payload,
        )
        try:
            self._bus.publish(env)
        except BusError as exc:
            raise SystemAgentCoordinationError(str(exc)) from exc
        return env

    def receive(self, agent_id: str) -> MessageEnvelope | None:
        """Consume the next effective message from an agent's inbox (data only)."""
        self._require_agent(agent_id)
        return self._bus.consume_next(agent_id)

    def queued_count(self, agent_id: str) -> int:
        self._require_agent(agent_id)
        return self._bus.queued_count(agent_id)

    def coordination_snapshot(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"task_id": task_id, "status": state.status.value}
            for task_id, state in sorted(self._states.items())
        )

    def _require_agent(self, agent_id: str) -> None:
        if agent_id not in self._runtime.registered_ids():
            raise UnknownSystemAgent(f"agent {agent_id!r} is not a registered system agent")


__all__ = ["SystemAgentCoordination"]