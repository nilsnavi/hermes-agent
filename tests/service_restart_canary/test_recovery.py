"""Test recovery: decision from durable evidence only, no blind restart."""
from agent.service_restart_canary.recovery import recovery_decision, RecoveryDecision, restart_as_rollback_denied


def test_unknown_evidence_manual():
    assert recovery_decision("EXECUTED", True, True, "UNKNOWN") == RecoveryDecision.MANUAL_REVIEW


def test_unknown_outcome_manual():
    assert recovery_decision("xo", False, False, "UNKNOWN_OUTCOME") == RecoveryDecision.MANUAL_REVIEW


def test_old_pid_survives_halt():
    assert recovery_decision("s", False, False, "OLD_PID_SURVIVES") == RecoveryDecision.HALT


def test_reconcile_running_healthy():
    assert recovery_decision("s", True, True, "NEW_VERIFIED") == RecoveryDecision.RECONCILE_RUNNING_HEALTHY


def test_reconcile_stopped():
    assert recovery_decision("s", True, False, "STOPPED") == RecoveryDecision.RECONCILE_STOPPED


def test_restart_as_rollback_denied():
    assert restart_as_rollback_denied() is True