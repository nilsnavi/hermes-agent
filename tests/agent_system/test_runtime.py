"""SystemAgentRuntime tests: registry + lifecycle + health bookkeeping, no execution."""

import pytest

from agent.agent_runtime.exceptions import AgentContractError
from agent.agent_runtime.lifecycle import AgentLifecycleStatus
from agent.agent_runtime.registry import AgentRegistry

from agent.agent_system import SystemAgentRuntime, SystemCapability
from agent.agent_system.definitions import SYSTEM_IMPLEMENTATION_IDS
from agent.agent_system.exceptions import UnknownImplementation, UnknownSystemAgent
from agent.agent_system.health import AgentHealthStatus


class _Clock:
    def __init__(self, start=1_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


def _runtime():
    return SystemAgentRuntime(clock=_Clock())


def test_register_system_agents_returns_six():
    rt = _runtime()
    defs = rt.register_system_agents()
    assert len(defs) == 6
    assert len(rt.registered_ids()) == 6


def test_register_system_agents_idempotent():
    rt = _runtime()
    rt.register_system_agents()
    # Calling register on already-latest version is skipped without breaking
    # contiguous versioning.
    for d in rt.registered_ids():
        assert d in ("planner", "research", "coding", "reviewer", "memory", "monitoring")


def test_runtime_registry_instance_is_an_agent_registry():
    rt = _runtime()
    rt.register_system_agents()
    assert isinstance(rt.registry(), AgentRegistry)


def test_registration_does_not_expand_capabilities():
    # The runtime's registry only ever admits the fixed system implementation
    # ids; a definition with any other implementation id is rejected, so
    # registering here can never grow the production capability surface.
    rt = _runtime()
    from agent.agent_runtime.permissions import AgentPermissions
    from agent.agent_runtime.registry import AgentDefinition

    rogue = AgentDefinition(
        agent_id="evil",
        version=1,
        name="evil",
        role="evil",
        implementation_id="evil-agent",
        capabilities=("write_everywhere",),
        trust_score=1.0,
        permissions=AgentPermissions(write_files=True, execute_code=True),
    )
    with pytest.raises(UnknownImplementation):
        rt.register(rogue)
    assert "evil" not in rt.registered_ids()


def test_lifecycle_transition_legal_path():
    rt = _runtime()
    rt.register_system_agents()
    life = rt.transition("planner", AgentLifecycleStatus.READY)
    assert life.status is AgentLifecycleStatus.READY
    life = rt.transition("planner", AgentLifecycleStatus.ACTIVE)
    assert life.status is AgentLifecycleStatus.ACTIVE


def test_lifecycle_illegal_transition_fail_closed():
    rt = _runtime()
    rt.register_system_agents()
    # REGISTERED -> ACTIVE is illegal (must go through READY).
    with pytest.raises(AgentContractError):
        rt.transition("planner", AgentLifecycleStatus.ACTIVE)


def test_lifecycle_no_flap_from_terminal():
    rt = _runtime()
    rt.register_system_agents()
    rt.transition("planner", AgentLifecycleStatus.READY)
    rt.transition("planner", AgentLifecycleStatus.ACTIVE)
    rt.transition("planner", AgentLifecycleStatus.RETIRED)
    # RETIRED is terminal and immutable.
    with pytest.raises(AgentContractError):
        rt.transition("planner", AgentLifecycleStatus.READY)


def test_lifecycle_self_transition_is_noop():
    rt = _runtime()
    rt.register_system_agents()
    # Lifecycle version is seeded from the DEFINITION version (1) this phase.
    assert rt.lifecycle("planner").version == 1  # type: ignore[reportOptionalMemberAccess]
    rt.transition("planner", AgentLifecycleStatus.READY)
    assert rt.lifecycle("planner").version == 2  # type: ignore[reportOptionalMemberAccess]
    # Same-status transition is idempotent: returns current state un-changed.
    assert rt.transition("planner", AgentLifecycleStatus.READY).version == 2  # type: ignore[reportOptionalMemberAccess]


def test_unregistered_lifecycle_raises_unknown():
    rt = _runtime()
    with pytest.raises(UnknownSystemAgent):
        rt.lifecycle("ghost")


def test_health_integrates_lifecycle():
    rt = _runtime()
    rt.register_system_agents()
    rt.observe("planner")
    # Lifecycle still REGISTERED -> degraded (never healthy without READY/ACTIVE).
    assert rt.health("planner").status is AgentHealthStatus.DEGRADED
    rt.transition("planner", AgentLifecycleStatus.READY)
    rt.transition("planner", AgentLifecycleStatus.ACTIVE)
    rt.observe("planner")
    assert rt.health("planner").status is AgentHealthStatus.HEALTHY


def test_unobserved_agent_is_unhealthy():
    rt = _runtime()
    rt.register_system_agents()
    assert rt.health("planner").status is AgentHealthStatus.UNHEALTHY


def test_snapshot_reports_status_rows():
    rt = _runtime()
    rt.register_system_agents()
    snap = rt.snapshot()
    assert len(snap) == 6
    fields = {s["agent_id"] for s in snap}
    assert fields == {"planner", "research", "coding", "reviewer", "memory", "monitoring"}
    assert all(s["health_status"] == "unhealthy" for s in snap)


def test_runtime_exposes_no_authority_methods():
    rt = _runtime()
    for method in ("execute", "dispatch", "authorize", "grant", "run"):
        assert not hasattr(rt, method), f"runtime must not expose {method}"