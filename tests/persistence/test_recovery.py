"""Recovery classification tests (Sprint 1.0.3 §20 / §21 / §36 / §38)."""

from agent.persistence.recovery import (
    RecoveryDisposition,
    classify,
)
from agent.runtime.states import RunStatus


def test_terminal_statuses():
    for status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        assert classify(status, []) is RecoveryDisposition.TERMINAL


def test_planning_safe_to_resume():
    assert classify(RunStatus.PLANNING, []) is RecoveryDisposition.SAFE_TO_RESUME


def test_classifying_safe_to_resume():
    assert classify(RunStatus.CLASSIFYING, []) is RecoveryDisposition.SAFE_TO_RESUME


def test_approved_safe_to_resume():
    assert classify(RunStatus.APPROVED, []) is RecoveryDisposition.SAFE_TO_RESUME


def test_waiting_approval_waits():
    assert classify(RunStatus.WAITING_APPROVAL, []) is RecoveryDisposition.WAIT_FOR_APPROVAL


def test_verifying_requires_verification():
    assert classify(RunStatus.VERIFYING, []) is RecoveryDisposition.REQUIRES_VERIFICATION


def test_tool_execution_with_started_only_is_manual_review():
    # §21/§38 — the mandatory crash case: TOOL_STARTED, no TOOL_COMPLETED.
    assert classify(
        RunStatus.TOOL_EXECUTION, ["STEP_STARTED", "TOOL_STARTED"]
    ) is RecoveryDisposition.MANUAL_REVIEW


def test_tool_execution_with_proof_of_completion_verifies():
    assert classify(
        RunStatus.TOOL_EXECUTION,
        ["STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED"],
    ) is RecoveryDisposition.REQUIRES_VERIFICATION


def test_running_with_inflight_tool_is_manual_review():
    assert classify(
        RunStatus.RUNNING, ["STEP_STARTED", "TOOL_STARTED"]
    ) is RecoveryDisposition.MANUAL_REVIEW


def test_running_between_steps_safe_to_resume():
    assert classify(
        RunStatus.RUNNING, ["STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED"]
    ) is RecoveryDisposition.SAFE_TO_RESUME


def test_running_no_events_requires_verification():
    assert classify(RunStatus.RUNNING, []) is RecoveryDisposition.REQUIRES_VERIFICATION


def test_created_is_safe_to_resume():
    assert classify(RunStatus.CREATED, []) is RecoveryDisposition.SAFE_TO_RESUME


def test_multiple_tool_cycles_last_one_inflight():
    """Two tool cycles; crash during the SECOND — still MANUAL_REVIEW."""
    events = [
        "STEP_STARTED", "TOOL_STARTED", "TOOL_COMPLETED",
        "STEP_STARTED", "TOOL_STARTED",
    ]
    assert classify(RunStatus.RUNNING, events) is RecoveryDisposition.MANUAL_REVIEW


def test_no_automatic_retry_guarantee():
    """Every non-terminal, non-approved disposition must NOT be SAFE_TO_RESUME
    when a tool was in flight — the crash contract."""
    for disposition in (
        RecoveryDisposition.MANUAL_REVIEW,
        RecoveryDisposition.REQUIRES_VERIFICATION,
    ):
        assert disposition is not RecoveryDisposition.SAFE_TO_RESUME
