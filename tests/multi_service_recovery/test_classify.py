"""Sprint 1.3.16 tests — deterministic classification, event order, global state."""
from __future__ import annotations

import pytest

from agent.multi_service_recovery.classify import (
    classify_disposition, derive_crash_point, event_order_valid,
    global_state_from_children,
)
from agent.multi_service_recovery.models import (CrashPoint, RecoveryDisposition)


def test_unknown_child_never_becomes_safe():
    d = classify_disposition(["GLOBAL_CLAIMED", "CHILD_SIMULATED"],
                             {"a": "UNKNOWN_OUTCOME"})
    assert d == RecoveryDisposition.MANUAL_REVIEW_REQUIRED


def test_empty_evidence_is_fail_closed():
    assert classify_disposition([], {}) == RecoveryDisposition.UNKNOWN_RECOVERY_STATE


def test_commit_requires_verify():
    assert event_order_valid(["GLOBAL_SIMULATED_COMMIT"]) is False
    assert event_order_valid(["SIMULATION_STARTED", "CHILD_SIMULATED",
                              "VERIFY_COMPLETED", "GLOBAL_SIMULATED_COMMIT"]) is True


def test_compensation_requires_effect():
    assert event_order_valid(["COMPENSATION_REQUIRED"]) is False
    assert event_order_valid(["SIMULATION_STARTED", "CHILD_SIMULATED",
                              "COMPENSATION_REQUIRED"]) is True


def test_barrier_requires_prepared_children():
    assert event_order_valid(["BARRIER_READY"]) is False


def test_verify_requires_execution_evidence():
    assert event_order_valid(["VERIFY_COMPLETED"]) is False
    assert event_order_valid(["SIMULATION_STARTED", "CHILD_SIMULATED",
                              "VERIFY_COMPLETED"]) is True


def test_terminal_then_mutation_event_is_corrupt():
    seq = ["SIMULATION_STARTED", "CHILD_SIMULATED", "VERIFY_COMPLETED",
           "GLOBAL_SIMULATED_COMMIT", "CHILD_SIMULATED"]
    assert event_order_valid(seq) is False
    assert classify_disposition(seq, {}) == RecoveryDisposition.MANUAL_REVIEW_REQUIRED


def test_crash_point_derivation_is_specific():
    assert derive_crash_point(["GLOBAL_CLAIMED"]) == CrashPoint.AFTER_GLOBAL_CLAIM
    assert derive_crash_point(["GLOBAL_CLAIMED", "CHILD_PREPARED"]) == CrashPoint.AFTER_CHILD_PREPARE
    assert derive_crash_point(["GLOBAL_CLAIMED", "SIMULATION_STARTED",
                               "CHILD_SIMULATED"]) == CrashPoint.AFTER_CHILD_A_SIMULATION


def test_verify_before_commit_is_continue_verify():
    seq = ["GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED",
           "CHILD_SIMULATED", "VERIFY_COMPLETED"]
    assert classify_disposition(seq, {}) == RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY


def test_durable_commit_is_terminal():
    seq = ["GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED",
           "CHILD_SIMULATED", "VERIFY_COMPLETED", "GLOBAL_SIMULATED_COMMIT"]
    assert classify_disposition(seq, {}) == RecoveryDisposition.TERMINAL


def test_compensation_required_is_not_success():
    seq = ["GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED",
           "COMPENSATION_REQUIRED"]
    assert classify_disposition(seq, {}) == RecoveryDisposition.COMPENSATION_REQUIRED


def test_global_state_never_partial_commit_success():
    assert global_state_from_children({"a": "VERIFIED", "b": "FAILED_SAFE",
                                       "c": "NOT_STARTED"}) == "COMPENSATION_REQUIRED"
    assert global_state_from_children({"a": "VERIFIED", "b": "UNKNOWN_OUTCOME",
                                       "c": "NOT_STARTED"}) == "UNKNOWN_OUTCOME"
    assert global_state_from_children({}) == "NOT_STARTED"


def test_global_committed_only_when_all_verified():
    assert global_state_from_children({"a": "VERIFIED", "b": "COMPENSATED"}) == "COMMITTED"
    assert global_state_from_children({"a": "VERIFIED", "b": "SIMULATED_EXECUTED"}) != "COMMITTED"