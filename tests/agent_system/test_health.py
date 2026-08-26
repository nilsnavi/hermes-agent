"""AgentHealthModel tests: fail-closed health semantics."""

import pytest

from agent.agent_runtime.lifecycle import AgentLifecycleStatus
from agent.agent_runtime.registry import AgentRegistry

from agent.agent_system.definitions import system_agent_definition, SystemAgentRole
from agent.agent_system.exceptions import AgentHealthError, UnknownSystemAgent
from agent.agent_system.health import AgentHealthModel, AgentHealthStatus


class _Clock:
    def __init__(self, start=1_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


def _registry():
    reg = AgentRegistry(allowed_implementation_ids={"planner-agent"})
    reg.register(system_agent_definition(SystemAgentRole.PLANNER))
    return reg


def _model(reg, *, ttl=60.0, lifecycle=None, clock=None):
    return AgentHealthModel(reg, lifecycle_status=lifecycle, ttl=ttl, clock=clock or _Clock())


def test_unregistered_agent_unknown():
    model = _model(_registry())
    with pytest.raises(UnknownSystemAgent):
        model.evaluate("nope")


def test_observe_unregistered_agent_fail_closed():
    model = _model(_registry())
    with pytest.raises(UnknownSystemAgent):
        model.observe("nope")


def test_never_observed_is_unhealthy():
    model = _model(_registry())
    report = model.evaluate("planner")
    assert report.status is AgentHealthStatus.UNHEALTHY
    assert report.version == 1


def test_stale_heartbeat_is_unhealthy():
    clock = _Clock(1000.0)
    model = _model(_registry(), ttl=60.0, clock=clock)
    model.observe("planner", now=1000.0)
    clock.t = 1100.0  # 100s later > ttl 60
    report = model.evaluate("planner")
    assert report.status is AgentHealthStatus.UNHEALTHY
    assert "stale" in report.reason


def test_fresh_heartbeat_without_lifecycle_provider_is_healthy():
    model = _model(_registry(), lifecycle=None, clock=_Clock(1000.0))
    model.observe("planner", now=1000.0)
    assert model.evaluate("planner").status is AgentHealthStatus.HEALTHY


def test_backward_clock_rejected():
    clock = _Clock(1000.0)
    model = _model(_registry(), clock=clock)
    model.observe("planner", now=1000.0)
    with pytest.raises(AgentHealthError):
        model.observe("planner", now=999.0)


def test_lifecycle_not_ready_is_unhealthy():
    def lifecycle(_a):
        return AgentLifecycleStatus.RETIRED

    model = _model(_registry(), lifecycle=lifecycle, clock=_Clock(1000.0))
    model.observe("planner", now=1000.0)
    assert model.evaluate("planner").status is AgentHealthStatus.UNHEALTHY


def test_lifecycle_distinct_value_invalid():
    def lifecycle(_a):
        return AgentLifecycleStatus.DISABLED

    model = _model(_registry(), lifecycle=lifecycle, clock=_Clock(1000.0))
    model.observe("planner", now=1000.0)
    assert model.evaluate("planner").status is AgentHealthStatus.UNHEALTHY


def test_registered_not_ready_is_degraded_not_healthy():
    def lifecycle(_a):
        return AgentLifecycleStatus.REGISTERED

    model = _model(_registry(), lifecycle=lifecycle, clock=_Clock(1000.0))
    model.observe("planner", now=1000.0)
    report = model.evaluate("planner")
    assert report.status is AgentHealthStatus.DEGRADED
    # Degraded is NOT healthy: fail-closed, never silently green.
    assert report.status is not AgentHealthStatus.HEALTHY


def test_ready_lifecycle_is_healthy():
    def lifecycle(_a):
        return AgentLifecycleStatus.READY

    model = _model(_registry(), lifecycle=lifecycle, clock=_Clock(1000.0))
    model.observe("planner", now=1000.0)
    assert model.evaluate("planner").status is AgentHealthStatus.HEALTHY


def test_ttl_must_be_positive():
    with pytest.raises(AgentHealthError):
        _model(_registry(), ttl=0)


def test_health_model_exposes_no_authority_methods():
    model = _model(_registry())
    for method in ("grant", "authorize", "execute", "dispatch"):
        assert not hasattr(model, method), f"health model must not expose {method}"


def test_report_to_dict_bounded():
    model = _model(_registry(), clock=_Clock(1000.0))
    model.observe("planner", now=1000.0)
    d = model.evaluate("planner").to_dict()
    assert d["status"] == "healthy"
    assert "agent_id" in d