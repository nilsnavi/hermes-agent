"""Sprint 1.3.10 — flags, allowlist, gates, restart/gateway deny."""
from __future__ import annotations

import pytest

from agent.service_reload_canary import (GateResult, Mode, RegisteredService,
                                         ReloadBudget, ServiceAllowlist, full_gate)
from agent.service_reload_canary.executor import assert_reload_only, deny_every_other_verb
from agent.service_reload_canary.exceptions import ServiceOperationDenied


def _svc(sid="hermes-webui"):
    return RegisteredService(sid, f"{sid}.service", "systemd", "user",
                             expected_executable=f"/usr/local/bin/{sid}",
                             expected_user="hermes",
                             expected_exec_reload="/bin/true",
                             profile_version=1)


def test_flags_off_by_default():
    from agent.service_reload_canary import flags
    assert flags.mode({}) == "off"
    assert flags.enabled({}) is False


def test_flags_unknown_mode_off():
    from agent.service_reload_canary import flags
    assert flags.mode({"HERMES_SERVICE_RELOAD_CANARY_V2_MODE": "execute"}) == "off"


def test_allowlist_exact():
    al = ServiceAllowlist([_svc()])
    assert al.get("hermes-webui") is not None
    assert al.get("hermes-gateway") is None
    assert not al.get("anyother")


def test_gate_canary_disabled():
    r = full_gate(mode="off", enabled=False, allowlisted=True, identity_verified=True,
                  graph_healthy=True, blast_service=True, config_valid=True,
                  pre_healthy=True, approval_valid=True, budget_ok=True, exec_reload_proven=True)
    assert r.ok is False and "CANARY_DISABLED" in r.reason


def test_gate_identity_drift():
    r = full_gate(mode="canary", enabled=True, allowlisted=True, identity_verified=False,
                  graph_healthy=True, blast_service=True, config_valid=True,
                  pre_healthy=True, approval_valid=True, budget_ok=True, exec_reload_proven=True)
    assert r.ok is False and "IDENTITY" in r.reason


def test_gate_config_invalid():
    r = full_gate(mode="canary", enabled=True, allowlisted=True, identity_verified=True,
                  graph_healthy=True, blast_service=True, config_valid=False,
                  pre_healthy=True, approval_valid=True, budget_ok=True, exec_reload_proven=True)
    assert r.ok is False and "CONFIG_INVALID" in r.reason


def test_gate_pre_health_failed():
    r = full_gate(mode="canary", enabled=True, allowlisted=True, identity_verified=True,
                  graph_healthy=True, blast_service=True, config_valid=True,
                  pre_healthy=False, approval_valid=True, budget_ok=True, exec_reload_proven=True)
    assert r.ok is False and "PRE_HEALTH" in r.reason


def test_gate_budget_exceeded():
    r = full_gate(mode="canary", enabled=True, allowlisted=True, identity_verified=True,
                  graph_healthy=True, blast_service=True, config_valid=True,
                  pre_healthy=True, approval_valid=True, budget_ok=False, exec_reload_proven=True)
    assert r.ok is False and "BUDGET" in r.reason


def test_gate_all_pass():
    r = full_gate(mode="canary", enabled=True, allowlisted=True, identity_verified=True,
                  graph_healthy=True, blast_service=True, config_valid=True,
                  pre_healthy=True, approval_valid=True, budget_ok=True, exec_reload_proven=True)
    assert r.ok is True


def test_restart_denied():
    with pytest.raises(ServiceOperationDenied):
        assert_reload_only("restart")
    with pytest.raises(ServiceOperationDenied):
        assert_reload_only("stop")
    with pytest.raises(ServiceOperationDenied):
        assert_reload_only("start")
    with pytest.raises(ServiceOperationDenied):
        assert_reload_only("kill")
    with pytest.raises(ServiceOperationDenied):
        assert_reload_only("daemon-reload")
    assert_reload_only("reload")  # only reload allowed


def test_all_non_reload_verbs_denied():
    from agent.service_reload_canary.executor import DENIED_VERBS
    for v in DENIED_VERBS:
        with pytest.raises(ServiceOperationDenied):
            assert_reload_only(v)


def test_budget_limits():
    b = ReloadBudget(None)
    assert b.can_attempt() is True
    for _ in range(ReloadBudget.__dict__.get("MAX_TOTAL_ATTEMPTS", 3)):
        b.record_attempt()
    assert b.can_attempt() is False
