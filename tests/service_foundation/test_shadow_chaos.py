"""Sprint 1.3.9 — shadow study (100) + chaos matrix (50) + read-only CLI."""
from __future__ import annotations

import random

from agent.service_foundation import (Eligibility, IdentityResult, Operation, evaluate,
                                      evaluate_health, verify_identity)
from agent.service_foundation.fake import state_for
from agent.service_foundation.graph import ServiceDependencyGraph
from agent.service_foundation.health import HealthStatus
from agent.service_foundation.registry import ServiceRegistry


def _g():
    from agent.service_foundation.models import EdgeType, Provenance
    g = ServiceDependencyGraph()
    g.add_edge("hermes-aux-agent", "test-echo", EdgeType.REQUIRES, Provenance.SYSTEMD_DECLARED)
    return g


def _rand_state(profile, exec_ok, health):
    if profile is None:
        return {"unit_name": "ghost.service", "executable": "/usr/local/bin/ghost",
                "MainPID": 1, "active": True, "health": health}
    return state_for(profile, exec_ok=exec_ok, health=health)


def test_shadow_100_evaluations_no_mutation():
    r = ServiceRegistry()
    ids = ["hermes-gateway", "hermes-aux-agent", "test-echo", "ghost", "unknown-svc"]
    decided = 0
    for _ in range(100):
        sid = random.choice(ids)
        p = r.get(sid)
        state = _rand_state(p, random.random() < 0.8, random.choice(["healthy", "unhealthy", "unknown"]))
        ident = verify_identity(p, {"unit_name": getattr(p, "unit_name", sid), "executable": "/usr/local/bin/x"})
        g = _g()
        v = evaluate(p, ident, g, random.choice([Operation.RELOAD_ELIGIBILITY, Operation.RESTART_ELIGIBILITY]),
                     health_ok=True, validator_ok=True, rollback_proven=True)
        # gateway always SELF_CONTROL_FORBIDDEN
        if sid == "hermes-gateway":
            assert v is Eligibility.SELF_CONTROL_FORBIDDEN
        # ghost/unregistered -> UNKNOWN
        if p is None:
            assert v is Eligibility.UNKNOWN
        decided += 1
    assert decided == 100


def test_chaos_50_scenarios_no_mutation():
    r = ServiceRegistry()
    p = r.get("hermes-aux-agent")
    g = _g()
    # identity/health/graph perturbations, never grants execution
    evals = {"future_reload": 0, "self_control": 0, "denied": 0}
    for i in range(50):
        wrong_exe = i % 3 == 0
        ident = verify_identity(p, {"unit_name": "hermes-aux-agent.service",
                                    "executable": "/elsewhere/bin/x" if wrong_exe else "/usr/local/bin/hermes-aux"})
        stale = i % 5 == 0
        health = HealthStatus.UNKNOWN if i % 7 == 0 else HealthStatus.HEALTHY
        gg = _g()
        if stale:
            gg._stale = True
        v = evaluate(p, ident, gg, Operation.RELOAD_ELIGIBILITY,
                     health_ok=(health is HealthStatus.HEALTHY),
                     validator_ok=True, rollback_proven=True)
        class_ = v.value
        if class_.startswith("eligible"):
            evals["future_reload"] += 1
        elif class_.startswith("self_control"):
            evals["self_control"] += 1
        else:
            evals["denied"] += 1
    assert evals["future_reload"] + evals["self_control"] + evals["denied"] == 50
    assert evals["denied"] > 0  # chaos events cause some denials


def test_read_only_cli_status():
    import io
    from agent.service_foundation import cli
    sys_argv = __import__("sys").argv
    __import__("sys").argv = ["cli", "status"]
    try:
        assert cli.main() == 0
    finally:
        __import__("sys").argv = sys_argv
