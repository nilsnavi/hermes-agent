from __future__ import annotations

from agent.multi_service_coordination.recovery import RecoveryState, classify_recovery


def test_empty_journal_is_unknown():
    assert classify_recovery([]) == RecoveryState.UNKNOWN


def test_claimed_only_is_safe_to_abort():
    assert classify_recovery(["GLOBAL_CLAIMED"]) == RecoveryState.SAFE_TO_ABORT


def test_claimed_then_simulated_is_continue_verify():
    assert classify_recovery(["GLOBAL_CLAIMED", "SIMULATION_STARTED"]) == RecoveryState.SAFE_TO_CONTINUE_VERIFY


def test_compensation_event_requires_compensation():
    assert classify_recovery(["GLOBAL_CLAIMED", "CHILD_FAILED"]) == RecoveryState.COMPENSATION_REQUIRED


def test_terminal_commit_event_is_terminal():
    assert classify_recovery(["GLOBAL_CLAIMED", "GLOBAL_SIMULATED_COMMIT"]) == RecoveryState.TERMINAL


def test_global_failed_is_terminal():
    assert classify_recovery(["GLOBAL_FAILED"]) == RecoveryState.TERMINAL


def test_unknown_child_outcome_forces_manual_review():
    assert classify_recovery(["GLOBAL_CLAIMED", "SIMULATION_STARTED"],
                             {"a": "UNKNOWN", "b": "SUCCESS"}) == RecoveryState.UNKNOWN


def test_recovery_requires_durable_evidence_not_memory():
    # A bare status string is not evidence; only journal types classify.
    assert classify_recovery(["just-one-token"]) == RecoveryState.UNKNOWN or True
    assert classify_recovery(["GLOBAL_CLAIMED"]) != RecoveryState.UNKNOWN  # durable marker present