"""Test preflight: typed gates immediately before adapter."""
import tempfile
from agent.service_restart_canary.preflight import RestartPreflight
from agent.service_restart_canary.budget import RestartBudget
from agent.service_restart_canary.breaker import RestartCircuitBreaker


def _run(**kw):
    d = tempfile.mkdtemp()
    pf = RestartPreflight(budget=RestartBudget(), breaker=RestartCircuitBreaker())
    defaults = dict(service_id="s", unit_identity_ok=True, old_pid_identity="p",
                    old_start_identity="si", identity_verified=True,
                    graph_healthy=True, blast_radius="SERVICE", dependents_count=0,
                    config_unchanged=True, pre_health_ok=True, port_ownership_ok=True,
                    no_orphan_children=True, executable_ok=True, user_ok=True,
                    cgroup_ok=True, plan_fresh=True, approval_valid=True)
    defaults.update(kw)
    return pf.run(**defaults)


def test_all_ok():
    assert _run().ok is True


def test_budget_exhausted():
    b = RestartBudget()
    b.allow_attempt(); b.allow_attempt()  # exhausted
    pf = RestartPreflight(budget=b, breaker=RestartCircuitBreaker())
    r = pf.run(service_id="s", unit_identity_ok=True, old_pid_identity="p",
               old_start_identity="si", identity_verified=True, graph_healthy=True,
               blast_radius="SERVICE", dependents_count=0, config_unchanged=True,
               pre_health_ok=True, port_ownership_ok=True, no_orphan_children=True,
               executable_ok=True, user_ok=True, cgroup_ok=True, plan_fresh=True,
               approval_valid=True)
    assert r.ok is False
    assert r.reason == "budget_exhausted"


def test_breaker_open_blocks():
    br = RestartCircuitBreaker()
    br.trip("UNKNOWN_OUTCOME")
    pf = RestartPreflight(budget=RestartBudget(), breaker=br)
    r = pf.run(service_id="s", unit_identity_ok=True, old_pid_identity="p",
               old_start_identity="si", identity_verified=True, graph_healthy=True,
               blast_radius="SERVICE", dependents_count=0, config_unchanged=True,
               pre_health_ok=True, port_ownership_ok=True, no_orphan_children=True,
               executable_ok=True, user_ok=True, cgroup_ok=True, plan_fresh=True,
               approval_valid=True)
    assert r.ok is False
    assert r.reason == "breaker_open"


def test_old_identity_missing():
    r = _run(old_pid_identity="", old_start_identity="")
    assert r.ok is False
    assert "identity" in r.reason


def test_graph_unhealthy():
    r = _run(graph_healthy=False)
    assert r.ok is False


def test_dependents():
    r = _run(dependents_count=1)
    assert r.ok is False


def test_prehealth_bad():
    r = _run(pre_health_ok=False)
    assert r.ok is False


def test_approval_invalid():
    r = _run(approval_valid=False)
    assert r.ok is False


def test_port_wrong():
    r = _run(port_ownership_ok=False)
    assert r.ok is False


def test_plan_stale():
    r = _run(plan_fresh=False)
    assert r.ok is False
    assert r.reason == "plan_stale"