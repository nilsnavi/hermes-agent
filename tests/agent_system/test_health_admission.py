"""Phase 5 hardening: AgentHealthModel.admission_status() is fail-closed.

Without fresh positive evidence and a READY lifecycle, an agent is NEVER
ADMISSIBLE. A standalone health model (no lifecycle provider) returns UNKNOWN,
closing the Phase 4 robustness gap.
"""

import pytest

from agent.agent_runtime.lifecycle import AgentLifecycleStatus

from agent.agent_system import SystemAgentRuntime
from agent.agent_system.exceptions import UnknownSystemAgent
from agent.agent_system.health import AgentAdmissionStatus, AgentHealthModel, AgentHealthStatus


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def _runtime(clock=None):
    return SystemAgentRuntime(clock=clock or Clock())


def _make_ready(rt, agent_id="coding"):
    rt.transition(agent_id, AgentLifecycleStatus.READY)
    rt.observe(agent_id)


def test_admission_status_fail_closed_without_ready_lifecycle():
    rt = _runtime()
    rt.register_system_agents()
    status, reason = rt.admission_status("coding")
    assert status is AgentAdmissionStatus.NOT_ADMISSIBLE
    assert "not ready" in reason


def test_admission_status_admissible_after_ready_and_observe():
    rt = _runtime()
    rt.register_system_agents()
    _make_ready(rt)
    status, reason = rt.admission_status("coding")
    assert status is AgentAdmissionStatus.ADMISSIBLE
    assert "lifecycle-ready" in reason


def test_admission_status_fail_closed_on_stale_heartbeat():
    clock = Clock()
    rt = _runtime(clock)
    rt.register_system_agents()
    _make_ready(rt)
    assert rt.admission_status("coding")[0] is AgentAdmissionStatus.ADMISSIBLE
    clock.t += 120.0  # advance beyond the default 60s TTL via the shared clock
    status, reason = rt.admission_status("coding")
    assert status is AgentAdmissionStatus.NOT_ADMISSIBLE
    assert "stale" in reason


def test_admission_status_fail_closed_on_no_heartbeat_even_when_ready():
    rt = _runtime()
    rt.register_system_agents()
    rt.transition("coding", AgentLifecycleStatus.READY)
    status, reason = rt.admission_status("coding")
    assert status is AgentAdmissionStatus.NOT_ADMISSIBLE
    assert "liveness" in reason


def test_admission_status_unknown_agent_raises():
    rt = _runtime()
    rt.register_system_agents()
    with pytest.raises(UnknownSystemAgent):
        rt.admission_status("ghost")


def test_health_is_unhealthy_without_positive_evidence():
    rt = _runtime()
    rt.register_system_agents()
    report = rt.health("coding")
    assert report.status is AgentHealthStatus.UNHEALTHY
    assert "never observed" in report.reason


def test_standalone_health_model_admission_is_unknown_fail_closed():
    rt = _runtime()
    rt.register_system_agents()
    model = AgentHealthModel(rt.registry(), clock=Clock())
    status, reason = model.admission_status("coding")
    assert status is AgentAdmissionStatus.UNKNOWN
    assert "lifecycle provider unavailable" in reason


def test_health_model_backward_clock_is_rejected():
    clock = Clock()
    rt = _runtime(clock)
    rt.register_system_agents()
    model = AgentHealthModel(
        rt.registry(),
        lifecycle_status=lambda _agent: AgentLifecycleStatus.READY,
        clock=clock,
    )
    model.observe("coding", now=100.0)
    with pytest.raises(Exception):
        model.observe("coding", now=50.0)  # earlier timestamp -> backward clock


def test_admission_status_is_never_green_for_retired_agent():
    rt = _runtime()
    rt.register_system_agents()
    _make_ready(rt)
    rt.transition("coding", AgentLifecycleStatus.ACTIVE)
    rt.transition("coding", AgentLifecycleStatus.RETIRED)
    status, reason = rt.admission_status("coding")
    assert status is AgentAdmissionStatus.NOT_ADMISSIBLE


def test_admission_status_requires_exact_agent_registry():
    with pytest.raises(Exception):
        AgentHealthModel("not-a-registry")  # type: ignore[arg-type]