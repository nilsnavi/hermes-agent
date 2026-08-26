"""SystemAgentCoordination tests: control-plane routing, state machine, messaging."""

import pytest

from agent.agent_orchestration.coordination import CoordinationStatus
from agent.agent_orchestration.messages import MessageType
from agent.agent_runtime.lifecycle import AgentLifecycleStatus

from agent.agent_system import SystemAgentCoordination, SystemAgentRuntime
from agent.agent_system.exceptions import (
    SystemAgentCoordinationError,
    UnknownSystemAgent,
)
from agent.agent_system.health import AgentHealthStatus


class _Clock:
    def __init__(self, start=1_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


def _ready_runtime(*agent_ids):
    rt = SystemAgentRuntime(clock=_Clock())
    rt.register_system_agents()
    for agent_id in agent_ids:
        rt.transition(agent_id, AgentLifecycleStatus.READY)
        rt.transition(agent_id, AgentLifecycleStatus.ACTIVE)
        rt.observe(agent_id)
    return rt


def _ready_healthy(*agent_ids):
    rt = _ready_runtime(*agent_ids)
    return SystemAgentCoordination(rt)


def test_start_returns_analyzing():
    coord = _ready_healthy("planner")
    st = coord.start("t-1")
    assert st.status is CoordinationStatus.ANALYZING
    assert st.is_terminal is False


def test_advance_legal_transitions():
    coord = _ready_healthy("planner")
    coord.start("t-1")
    coord.advance("t-1", CoordinationStatus.PLANNING)
    coord.advance("t-1", CoordinationStatus.ROUTING)
    st = coord.advance("t-1", CoordinationStatus.SUPERVISING)
    assert st.status is CoordinationStatus.SUPERVISING


def test_advance_illegal_transition_fail_closed():
    coord = _ready_healthy("planner")
    coord.start("t-1")
    with pytest.raises(SystemAgentCoordinationError):
        # ANALYZING -> SUPERVISING skips required phases; illegal.
        coord.advance("t-1", CoordinationStatus.SUPERVISING)


def test_advance_skips_coordination_never_executes():
    coord = _ready_healthy("planner")
    for method in ("execute", "dispatch", "authorize", "grant", "run"):
        assert not hasattr(coord, method), f"coordination must not expose {method}"


def test_availability_only_healthy_agents():
    # Only 'planner' is made healthy; others remain unobserved -> excluded.
    coord = _ready_healthy("planner")
    assert coord.availability() == frozenset({"planner"})


def test_route_selects_healthy_capable_agent():
    # research, coding, reviewer, memory healthy; planner NOT healthy.
    coord = _ready_healthy("research", "coding", "reviewer", "memory")
    sel = coord.route(required_capability="research")
    assert sel.agent_id == "research"


def test_route_rejects_unhealthy_capability_owner():
    # Only research is capable of 'research'; not made healthy -> unavailable.
    coord = _ready_healthy("coding")
    with pytest.raises(SystemAgentCoordinationError):
        coord.route(required_capability="research")


def test_send_delivers_data_message():
    coord = _ready_healthy("planner", "research")
    env = coord.send(task_id="t-1", from_agent="planner", to_agent="research", payload=("hi",))
    assert coord.queued_count("research") == 1
    got = coord.receive("research")
    assert got is not None
    assert got.payload == ("hi",)
    assert env.type is MessageType.REQUEST


def test_send_rejects_unregistered_agent():
    coord = _ready_healthy("planner")
    with pytest.raises(UnknownSystemAgent):
        coord.send(task_id="t-1", from_agent="planner", to_agent="ghost", payload=())


def test_receive_requires_registered_agent():
    coord = _ready_healthy("planner")
    with pytest.raises(UnknownSystemAgent):
        coord.receive("ghost")


def test_coordination_snapshot():
    coord = _ready_healthy("planner")
    coord.start("a")
    coord.advance("a", CoordinationStatus.PLANNING)
    coord.start("b")
    snap = coord.coordination_snapshot()
    assert {s["task_id"] for s in snap} == {"a", "b"}
    by_id = {s["task_id"]: s["status"] for s in snap}
    assert by_id["a"] == "planning"
    assert by_id["b"] == "analyzing"


def test_agent_message_is_data_not_authority():
    coord = _ready_healthy("planner", "research")
    env = coord.send(task_id="t-1", from_agent="planner", to_agent="research", payload=("x",))
    for method in ("execute", "dispatch", "grant", "authorize"):
        assert not hasattr(env, method), f"message must not expose {method}"
    assert env.payload == ("x",)


def test_planner_and_supervisor_are_dispositions_not_executors():
    # Coordination exposes routing + state only; no method resembles execution.
    coord = _ready_healthy("planner")
    methods = {name for name in vars(type(coord))}
    assert not ({"execute", "dispatch", "run", "authorize", "grant"} & methods)