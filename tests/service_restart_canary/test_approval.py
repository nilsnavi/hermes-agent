"""Test approval: single-use, bound, drift invalidates, TTL expiry."""
import time
from agent.service_restart_canary.approval import ApprovalManager, plan_hash_of
from agent.service_restart_canary.models import RestartApproval


def _mk(**kw):
    defaults = dict(
        approval_id="a1", service_id="hermes-aux-canary", profile_version=1,
        operation="RESTART", old_pid_identity="pid/100/si", old_start_identity="si",
        graph_digest="gd", ports=(9000,), config_hash="ch", pre_health="HEALTHY",
        risk="HIGH", blast_radius="SERVICE", quiescence_contract="q", startup_contract="s",
        rollback_plan="r", baseline_sha="sha", ttl=300.0, created_at=time.time(),
    )
    defaults.update(kw)
    return RestartApproval(**defaults)


def test_create_approval():
    mgr = ApprovalManager()
    a = mgr.create(_mk())
    assert a.approval_id == "a1"
    assert a.service_id == "hermes-aux-canary"


def test_validate_ok():
    mgr = ApprovalManager()
    mgr.create(_mk())
    ok, why = mgr.validate("a1", "hermes-aux-canary", "RESTART",
                           "pid/100/si", "si", "gd", "ch", "HEALTHY")
    assert ok is True
    assert why == "approval_valid"


def test_consume_single_use():
    mgr = ApprovalManager()
    mgr.create(_mk())
    assert mgr.consume("a1") is True
    # second consume fails
    assert mgr.consume("a1") is False
    ok, why = mgr.validate("a1", "hermes-aux-canary")
    assert ok is False
    assert why == "approval_used"


def test_drift_identity_invalid():
    mgr = ApprovalManager()
    mgr.create(_mk())
    ok, why = mgr.validate("a1", "hermes-aux-canary", "RESTART",
                           "pid/WRONG/si", "si", "gd", "ch", "HEALTHY")
    assert ok is False
    assert "drift" in why


def test_drift_graph_invalid():
    mgr = ApprovalManager()
    mgr.create(_mk())
    ok, why = mgr.validate("a1", "hermes-aux-canary", "RESTART",
                           "pid/100/si", "si", "WRONG", "ch", "HEALTHY")
    assert ok is False
    assert "graph" in why


def test_drift_config_invalid():
    mgr = ApprovalManager()
    mgr.create(_mk())
    ok, why = mgr.validate("a1", "hermes-aux-canary", "RESTART",
                           "pid/100/si", "si", "gd", "WRONG", "HEALTHY")
    assert ok is False
    assert "config" in why


def test_expired():
    mgr = ApprovalManager()
    mgr.create(_mk(ttl=1.0, created_at=time.time() - 100))
    ok, why = mgr.validate("a1", "hermes-aux-canary", "RESTART",
                           "pid/100/si", "si", "gd", "ch", "HEALTHY")
    assert ok is False
    assert "expired" in why


def test_plan_hash_stable():
    a = _mk()
    h1 = plan_hash_of(a)
    h2 = plan_hash_of(a)
    assert h1 == h2
    assert len(h1) == 32
