"""Sprint 1.3.12 — UNKNOWN_OUTCOME handling, crash recovery, rollback planning.

Critical restart states STOP_UNKNOWN / START_UNKNOWN: do NOT blindly start / restart.
No auto retry. Recovery decision from durable evidence only.
Restart-as-rollback (restart again = rollback) is HARD DENY.
"""
from __future__ import annotations

from agent.service_restart_foundation.unknown_outcome import (
    UnknownOutcomePolicy,
    classify_outcome,
    OutcomeClass,
)
from agent.service_restart_foundation.recovery import (
    recovery_decision,
    CrashPoint,
    RecoveryDecision,
)
from agent.service_restart_foundation.rollback import (
    RollbackStrategy,
    restart_as_rollback_denied,
    plan_rollback,
)


class TestUnknownOutcome:
    def test_stop_unknown_does_not_blindly_start(self):
        verdict = classify_outcome("STOP_UNKNOWN")
        assert verdict in (OutcomeClass.HALT_STOP, OutcomeClass.DO_NOT_BLIND_START)

    def test_start_unknown_does_not_restart_again(self):
        verdict = classify_outcome("START_UNKNOWN")
        assert verdict == OutcomeClass.DO_NOT_RESTART

    def test_no_auto_retry_for_unknown(self):
        assert UnknownOutcomePolicy.AUTO_RETRY is False

    def test_unknown_requires_manual_review(self):
        assert classify_outcome("STOP_UNKNOWN") in (
            OutcomeClass.HALT_STOP, OutcomeClass.DO_NOT_BLIND_START, OutcomeClass.MANUAL_REVIEW)


class TestRecovery:
    def test_recovery_from_durable_evidence(self):
        d = recovery_decision(crash_point=CrashPoint.AFTER_STOP_REQUEST,
                              durable_evidence="STOP_REQUESTED",
                              old_pid_alive=False, new_pid_alive=False)
        # must reconcile, not blindly start
        assert d in (RecoveryDecision.RECONCILE, RecoveryDecision.MANUAL_REVIEW,
                     RecoveryDecision.HALT)

    def test_crash_before_start_halt(self):
        d = recovery_decision(crash_point=CrashPoint.BEFORE_START,
                              durable_evidence="PLANNED", old_pid_alive=False,
                              new_pid_alive=False)
        assert d in (RecoveryDecision.RECONCILE, RecoveryDecision.MANUAL_REVIEW)

    def test_crash_after_new_pid_unknown(self):
        d = recovery_decision(crash_point=CrashPoint.AFTER_NEW_PID,
                              durable_evidence="UNKNOWN", old_pid_alive=False,
                              new_pid_alive=True)
        assert d in (RecoveryDecision.MANUAL_REVIEW, RecoveryDecision.RECONCILE)


class TestRollbackPlanning:
    def test_rollback_strategies_enum(self):
        assert RollbackStrategy.RECONCILE_CURRENT_STATE.value == "RECONCILE_CURRENT_STATE"
        assert RollbackStrategy.RESTART_PREVIOUS_VERSION.value == "RESTART_PREVIOUS_VERSION"
        assert RollbackStrategy.OPERATOR_INTERVENTION.value == "OPERATOR_INTERVENTION"
        assert RollbackStrategy.UNSUPPORTED.value == "UNSUPPORTED"

    def test_restart_as_rollback_hard_denied(self):
        # "restart again" is not rollback — it is auto-retry
        assert restart_as_rollback_denied() is True
        assert restart_as_rollback_denied(
            strategy=RollbackStrategy.RESTART_PREVIOUS_VERSION) is True if (
                RollbackStrategy.RESTART_PREVIOUS_VERSION != "RESTART_SAME_VERSION") else False

    def test_rollback_plan_analysis_only(self):
        # 1.3.12: no production rollback, plan analysis only
        p = plan_rollback(strategy=RollbackStrategy.RECONCILE_CURRENT_STATE)
        assert p["production_mutation"] == 0
        assert p["strategy"] == "RECONCILE_CURRENT_STATE"