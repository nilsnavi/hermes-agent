"""Sprint 1.3.8 — production_policy: profiles, registry, risk, blast, deny."""
from __future__ import annotations

import os

import pytest

from agent.production_policy import (BlastRadius, ConsumerClass, PolicyEngine,
                                     RiskClass, build_profiles, hard_denied_operation,
                                     hard_denied_path)
from agent.production_policy.exceptions import (ApprovalInvalid, BlastRadiusBlocked,
                                                BudgetExceeded, CircuitBreakerOpen,
                                                ConsumerUnknownBlocked, OperationNotAllowed,
                                                PolicyDenied, ProfileDisabled,
                                                TargetNotRegistered)
from agent.production_policy.models import (ProductionResourceProfile, Operation,
                                            TargetRegistration, validate_target_name)
from agent.production_policy.risk import effective_risk
from agent.production_policy.budget import DurableBudget


def _profiles(tmp_path):
    e = PolicyEngine(target_store_dir=str(tmp_path))
    for pid in e.profiles:
        e.profiles[pid] = _enable(e.profiles[pid])
    return e


def _enable(p):
    import dataclasses
    return dataclasses.replace(p, enabled=True)


def _mk(tmp_path, name):
    import dataclasses
    e = PolicyEngine(target_store_dir=str(tmp_path))
    for pid in e.profiles:
        p = e.profiles[pid]
        base = os.path.join(str(tmp_path), pid.lower())
        os.makedirs(base, exist_ok=True)
        e.profiles[pid] = dataclasses.replace(_enable(p), exact_target_dir=base + "/")
        e.targets[pid][name] = TargetRegistration(
            profile_id=pid, target_id=name, resolved_path=os.path.join(base, name + ".json"),
            realpath=os.path.join(base, name + ".json"), owner="hermes", mode=0o600)
    return e


def test_profiles_immutable_and_three():
    b = build_profiles()
    assert set(b) == {"P1-MARKER", "P2-JSON", "P3-TEXT"}
    assert all(isinstance(p, ProductionResourceProfile) for p in b.values())
    assert all(p.enabled is False for p in b.values())  # off by default


def test_validate_target_name():
    validate_target_name("alice-marker")
    for bad in ("..", ".", "a/b", "a\\b", "var:", "-x", "config.yaml", "A b", "x" * 70):
        with pytest.raises(ValueError):
            validate_target_name(bad)


def test_hard_deny_paths():
    for p in ["/etc/passwd", "/usr/bin/x", "/run/x", "/var/lib/x", "/proc/1",
              "/sys/x", "/dev/x", "/home/hermes/.ssh/id_rsa",
              os.path.expanduser("~/.hermes/config.yaml"),
              os.path.expanduser("~/.hermes/state.db"),
              os.path.expanduser("~/.hermes/.env")]:
        assert hard_denied_path(p), p


def test_hard_deny_ops():
    for op in ["system_control", "service_restart", "scheduler_change",
               "provider_change", "network_change", "firewall_change",
               "cron_change", "docker_change", "systemd_change", "package_change"]:
        assert hard_denied_operation(op)


def test_effective_risk_monotonic():
    assert effective_risk(RiskClass.LOW_MUTATION, ConsumerClass.NO_RUNTIME_CONSUMER) == RiskClass.LOW_MUTATION
    assert effective_risk(RiskClass.LOW_MUTATION, ConsumerClass.PASSIVE_READ_CONSUMER) == RiskClass.MEDIUM_MUTATION
    assert effective_risk(RiskClass.LOW_MUTATION, ConsumerClass.ACTIVE_CONSUMER) == RiskClass.HIGH_MUTATION
    assert effective_risk(RiskClass.LOW_MUTATION, ConsumerClass.UNKNOWN) == RiskClass.HIGH_MUTATION


def test_register_target_eats_escape(tmp_path):
    e = _mk(tmp_path, "x")
    with pytest.raises(ValueError):
        e.register_target("P1-MARKER", "../escape")


def test_deny_wrong_operation(tmp_path):
    e = _mk(tmp_path, "m")
    with pytest.raises(OperationNotAllowed):
        e.evaluate(profile_id="P1-MARKER", target="m", operation="update_json",
                   payload_hash="h", approval=None)
    with pytest.raises(OperationNotAllowed):
        e.evaluate(profile_id="P1-MARKER", target="m", operation="system_restart",
                   payload_hash="h", approval=None)


def test_deny_unregistered_target(tmp_path):
    e = _mk(tmp_path, "m")
    with pytest.raises(TargetNotRegistered):
        e.evaluate(profile_id="P1-MARKER", target="ghost", operation="set_marker",
                   payload_hash="h", approval=None, resource_mode="limited")


def test_deny_profile_disabled(tmp_path):
    e = PolicyEngine(target_store_dir=str(tmp_path))  # profiles disabled by default
    with pytest.raises(ProfileDisabled):
        e.evaluate(profile_id="P1-MARKER", target="m", operation="set_marker",
                   payload_hash="h", approval=None, resource_mode="limited")


def test_blast_radius_block(tmp_path):
    import dataclasses
    e = _mk(tmp_path, "m")
    e.profiles["P1-MARKER"] = dataclasses.replace(
        e.profiles["P1-MARKER"], blast_radius_ceiling=BlastRadius.SERVICE)
    with pytest.raises(BlastRadiusBlocked):
        e.evaluate(profile_id="P1-MARKER", target="m", operation="set_marker",
                   payload_hash="h", approval=None, resource_mode="limited")


def test_consumer_unknown_block(tmp_path):
    import dataclasses
    e = _mk(tmp_path, "m")
    e.profiles["P1-MARKER"] = dataclasses.replace(
        e.profiles["P1-MARKER"], consumer_class=ConsumerClass.UNKNOWN)
    with pytest.raises(ConsumerUnknownBlocked):
        e.evaluate(profile_id="P1-MARKER", target="m", operation="set_marker",
                   payload_hash="h", approval=None, resource_mode="limited")


def test_approval_required_not_given(tmp_path):
    e = _mk(tmp_path, "m")
    r = e.evaluate(profile_id="P1-MARKER", target="m", operation="set_marker",
                   payload_hash="h", approval=None, resource_mode="limited")
    assert r["allowed"] is False and r["reason"] == "approval required"


def test_approval_bound_proof(tmp_path, monkeypatch):
    import time as _t
    e = _mk(tmp_path, "m")
    appr = {"profile": "P1-MARKER", "profile_version": 1, "operation": "set_marker",
            "target": "m", "payload_hash": "h", "expires_ts": _t.time() + 60}
    r = e.evaluate(profile_id="P1-MARKER", target="m", operation="set_marker",
                   payload_hash="h", approval=appr, resource_mode="limited")
    assert r["allowed"] is True
    # wrong version
    bad = dict(appr, profile_version=2)
    with pytest.raises(ApprovalInvalid):
        e.evaluate(profile_id="P1-MARKER", target="m", operation="set_marker",
                   payload_hash="h", approval=bad, resource_mode="limited")
    # expired
    exp = dict(appr, expires_ts=_t.time() - 1)
    with pytest.raises(ApprovalInvalid):
        e.evaluate(profile_id="P1-MARKER", target="m", operation="set_marker",
                   payload_hash="h", approval=exp, resource_mode="limited")


def test_budget_exhausted(tmp_path):
    e = _mk(tmp_path, "m")
    appr = {"profile": "P1-MARKER", "profile_version": 1, "operation": "set_marker",
            "target": "m", "payload_hash": "h", "expires_ts": 2 ** 40}
    b = e._budget
    spec = e.profiles["P1-MARKER"].budget
    for _ in range(spec.max_attempts_per_hour):
        b.record_attempt("P1-MARKER")
    with pytest.raises(BudgetExceeded):
        e.evaluate(profile_id="P1-MARKER", target="m", operation="set_marker",
                   payload_hash="h", approval=appr, resource_mode="limited")


def test_circuit_breaker_opens(tmp_path):
    b = DurableBudget(str(tmp_path / "b.json"))
    b.bump("P1-MARKER", "consecutive_verify", 2)
    assert b.circuit_open("P1-MARKER") is True
    e = _mk(tmp_path, "m")  # enables profiles + registers target "m"
    e._budget = b
    appr = {"profile": "P1-MARKER", "profile_version": 1, "operation": "set_marker",
            "target": "m", "payload_hash": "h", "expires_ts": 2 ** 40}
    with pytest.raises(CircuitBreakerOpen):
        e.evaluate(profile_id="P1-MARKER", target="m", operation="set_marker",
                   payload_hash="h", approval=appr, resource_mode="limited")
