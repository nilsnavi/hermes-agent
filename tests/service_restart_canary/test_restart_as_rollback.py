"""Test restart-as-rollback is hard denied (no second restart to fix a failure)."""
from agent.service_restart_canary.recovery import restart_as_rollback_denied


def test_restart_as_rollback_denied():
    assert restart_as_rollback_denied() is True


def test_no_retry_marker():
    # Auto-retry of a failed restart must never be used as rollback strategy.
    from agent.service_restart_canary.models import ServiceRestartCanaryPlan
    p = ServiceRestartCanaryPlan(transaction_id="t", service_id="s", profile_version=1)
    assert p.recovery_strategy != "RESTART_SAME_VERSION"