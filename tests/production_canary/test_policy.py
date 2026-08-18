"""Sprint 1.3.7 §6/§11/§24 — policy gate, approval binding, system-control deny."""
from __future__ import annotations

import time

import pytest

from agent.production_canary.approval import ApprovalRegistry, fingerprint_target, plan_hash
from agent.production_canary.capability import decide, risk_class
from agent.production_canary.core import CANARY_CAPABILITY, CANARY_OPERATION
from agent.production_canary.deny import check_deny, SystemControlDeny
from agent.production_canary.flags import Mode


def test_risk_is_mutation_not_readonly():
    assert risk_class(CANARY_CAPABILITY) == "LOW_MUTATION"
    assert risk_class("SYSTEM_WRITE") == "DENY"


def test_policy_allows_when_all_conditions():
    d = decide(CANARY_CAPABILITY, target="t", operation=CANARY_OPERATION,
               target_allowed=True, approval_valid=True, baseline_ok=True,
               health_ok=True, mode=Mode.CANARY, enabled=True)
    assert d.allowed is True


@pytest.mark.parametrize("over,reason", [
    ({"capability": "SYSTEM_CONTROL"}, "capability not allowed"),
    ({"operation": "SYSTEM_ACTION"}, "operation not allowed"),
    ({"target_allowed": False}, "target not in exact allowlist"),
    ({"approval_valid": False}, "explicit approval invalid/missing"),
    ({"baseline_ok": False}, "baseline mismatch"),
    ({"health_ok": False}, "health not green"),
    ({"mode": Mode.SHADOW}, "canary mode not active"),
    ({"enabled": False}, "canary flag not enabled"),
])
def test_policy_denies_any_missing_condition(over, reason):
    base = dict(capability=CANARY_CAPABILITY, target="t", operation=CANARY_OPERATION,
                target_allowed=True, approval_valid=True, baseline_ok=True,
                health_ok=True, mode=Mode.CANARY, enabled=True)
    base.update(over)
    d = decide(base.pop("capability"), **base)
    assert d.allowed is False
    assert reason in d.reason


# ---- approval binding ----
def _grant(reg, **kw):
    base = dict(transaction_id="tx1", plan_hash="ph", target_fingerprint="tf",
                before_hash="b", expected_after_hash="a", operation=CANARY_OPERATION,
                risk="LOW_MUTATION", baseline_sha="bs")
    base.update(kw)
    return reg.grant(**base)


def test_approval_single_use():
    reg = ApprovalRegistry()
    a = _grant(reg)
    ok1 = reg.validate_and_consume(a.approval_id, plan_hash="ph", target_fingerprint="tf",
                                   before_hash="b", expected_after_hash="a",
                                   operation=CANARY_OPERATION, risk="LOW_MUTATION",
                                   baseline_sha="bs")
    ok2 = reg.validate_and_consume(a.approval_id, plan_hash="ph", target_fingerprint="tf",
                                   before_hash="b", expected_after_hash="a",
                                   operation=CANARY_OPERATION, risk="LOW_MUTATION",
                                   baseline_sha="bs")
    assert ok1 is True and ok2 is False  # single use


def test_approval_plan_change_invalidates():
    reg = ApprovalRegistry()
    a = _grant(reg)
    # different plan_hash than approved -> invalid
    ok = reg.validate_and_consume(a.approval_id, plan_hash="DIFFERENT", target_fingerprint="tf",
                                  before_hash="b", expected_after_hash="a",
                                  operation=CANARY_OPERATION, risk="LOW_MUTATION",
                                  baseline_sha="bs")
    assert ok is False


def test_approval_ttl_expiry():
    reg = ApprovalRegistry()
    a = _grant(reg, ttl=5, issued_at=time.time() - 100)
    ok = reg.validate_and_consume(a.approval_id, plan_hash="ph", target_fingerprint="tf",
                                  before_hash="b", expected_after_hash="a",
                                  operation=CANARY_OPERATION, risk="LOW_MUTATION",
                                  baseline_sha="bs", now=time.time())
    assert ok is False  # expired


def test_approval_after_hash_binding():
    reg = ApprovalRegistry()
    a = _grant(reg)
    # different expected-after-hash than approved -> invalid (plan drift)
    ok = reg.validate_and_consume(a.approval_id, plan_hash="ph", target_fingerprint="tf",
                                  before_hash="b", expected_after_hash="CHANGED",
                                  operation=CANARY_OPERATION, risk="LOW_MUTATION",
                                  baseline_sha="bs")
    assert ok is False


# ---- system-control deny regression (§24) ----
@pytest.mark.parametrize("op", ["SYSTEMCTL", "SERVICE_CONTROL", "KILL", "PKILL",
                                "GATEWAY_RESTART", "SCHEDULER_MUTATION",
                                "PROVIDER_MUTATION", "NETWORK_CONFIG", "FIREWALL",
                                "DOCKER", "PACKAGE_MANAGEMENT", "SSH", "CRON"])
def test_system_control_always_denied(op):
    d = check_deny(target="/fake", operation=op, mode=Mode.CANARY)
    assert d.allowed is False
    assert "denied" in d.reason
