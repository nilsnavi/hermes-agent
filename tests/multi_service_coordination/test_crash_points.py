from __future__ import annotations

"""Crash matrix (brief §35).  A crash at any checkpoint must leave durable
evidence that classifies to a fail-closed recovery disposition -- never a
false SUCCESS, never an auto-retry.
"""
from agent.multi_service_coordination.recovery import RecoveryState, classify_recovery


def _crash(*types):
    return classify_recovery(list(types)).value


def test_after_global_claim():
    assert _crash("GLOBAL_CLAIMED") == RecoveryState.SAFE_TO_ABORT.value


def test_after_lock_a():
    # claimed, lock A acquired, crash before lock B -> safe abort
    assert _crash("GLOBAL_CLAIMED", "LOCK_ACQUIRED").startswith("SAFE_TO")


def test_after_lock_b():
    assert _crash("GLOBAL_CLAIMED", "LOCK_ACQUIRED").startswith("SAFE_TO")


def test_after_all_locks():
    assert _crash("GLOBAL_CLAIMED", "LOCK_ACQUIRED").startswith("SAFE_TO")


def test_after_prepare_a_and_b():
    assert _crash("GLOBAL_CLAIMED", "LOCK_ACQUIRED", "CHILD_PREPARED",
                  "CHILD_PREPARED", "BARRIER_READY").startswith("SAFE_TO")


def test_after_barrier_ready():
    assert _crash("GLOBAL_CLAIMED", "LOCK_ACQUIRED", "CHILD_PREPARED",
                  "BARRIER_READY").startswith("SAFE_TO")


def test_after_simulated_execution_a():
    assert _crash("GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED") == \
        RecoveryState.SAFE_TO_CONTINUE_VERIFY.value


def test_before_verify():
    assert _crash("GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED",
                  "CHILD_SIMULATED") == RecoveryState.SAFE_TO_CONTINUE_VERIFY.value


def test_during_compensation_classification():
    assert _crash("GLOBAL_CLAIMED", "CHILD_FAILED") == RecoveryState.COMPENSATION_REQUIRED.value


def test_before_simulated_commit():
    # verify completed but commit event absent -> never treated as committed
    disp = classify_recovery(["GLOBAL_CLAIMED", "VERIFY_COMPLETED"])
    assert disp != RecoveryState.TERMINAL
    assert disp.value.startswith("SAFE_TO")


def test_no_auto_retry_ever():
    """A crash never produces a decision that implies blind replay."""
    # terminal evidence is terminal, never auto-retried
    assert classify_recovery(["GLOBAL_SIMULATED_COMMIT"]) == RecoveryState.TERMINAL
    assert classify_recovery(["GLOBAL_FAILED"]) == RecoveryState.TERMINAL
    assert classify_recovery(["COMPENSATION_REQUIRED"]) == RecoveryState.COMPENSATION_REQUIRED
    # ambiguous (claimed, simulated) must ask for verification, never replay
    assert classify_recovery(["GLOBAL_CLAIMED", "SIMULATION_STARTED"]) == \
        RecoveryState.SAFE_TO_CONTINUE_VERIFY


def test_crash_on_unknown_child_is_manual_review():
    assert classify_recovery(["GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED"],
                             {"a": "UNKNOWN", "b": "SUCCESS"}) == RecoveryState.UNKNOWN


def test_coordination_crash_never_reports_partial_commit_success():
    # a partial journal with a CHILD_FAILED must be COMPENSATION, never SUCCESS
    assert _crash("GLOBAL_CLAIMED", "LOCK_ACQUIRED", "SIMULATION_STARTED",
                  "CHILD_SIMULATED", "CHILD_FAILED") == RecoveryState.COMPENSATION_REQUIRED.value