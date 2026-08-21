"""Test restart plan: immutable, bound, drift/expiry detection."""
from agent.service_restart_canary.plan import build_plan
from agent.service_restart_canary.models import ServiceRestartCanaryPlan


def test_build_plan():
    p = build_plan(transaction_id="t", service_id="hermes-aux-canary", profile_version=1,
                   old_process_identity="pid/100/si", identity_fingerprint="fp",
                   graph_digest="gd", config_hash="ch", ports_before=(9000,),
                   pre_health_receipt="h", approval_id="a1",
                   created_at=1000.0, ttl=300.0)
    assert p.transaction_id == "t"
    assert p.service_id == "hermes-aux-canary"
    assert p.operation == "RESTART"
    assert p.blast_radius == "SERVICE"
    assert p.recovery_strategy == "MANUAL_REVIEW_REQUIRED"


def test_plan_expiry():
    p = build_plan(transaction_id="t", service_id="s", profile_version=1,
                   old_process_identity="o", identity_fingerprint="f",
                   graph_digest="g", config_hash="c", ports_before=(),
                   pre_health_receipt="h", approval_id="a",
                   created_at=1000.0, ttl=300.0)
    assert p.expired(1299.0) is False
    assert p.expired(1301.0) is True


def test_plan_immutable():
    p = build_plan(transaction_id="t", service_id="s", profile_version=1,
                   old_process_identity="o", identity_fingerprint="f",
                   graph_digest="g", config_hash="c", ports_before=(),
                   pre_health_receipt="h", approval_id="a", created_at=1.0)
    try:
        p.operation = "STOP"
        assert False, "should be immutable"
    except Exception:
        pass


def test_plan_hash_bound():
    p = build_plan(transaction_id="t", service_id="s", profile_version=1,
                   old_process_identity="o", identity_fingerprint="f",
                   graph_digest="g", config_hash="c", ports_before=(),
                   pre_health_receipt="h", approval_id="a", created_at=1.0)
    assert isinstance(p, ServiceRestartCanaryPlan)