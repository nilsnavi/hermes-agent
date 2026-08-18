"""Sprint 1.3.2 §5 — canonical status model + §3/§4 serialization."""

from datetime import datetime, timezone

import pytest

from agent.verified_tool_executor.models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    TERMINAL_STATUSES,
    is_metadata_allowed,
    side_effect_report_compatible_with_read_only,
)


def test_canonical_statuses_complete():
    """§5 — the full canonical set exists, UNKNOWN_OUTCOME mandatory."""
    expected = {
        "PENDING", "STARTED", "SUCCEEDED", "FAILED", "TIMED_OUT",
        "CANCELLED", "REJECTED", "UNKNOWN_OUTCOME",
    }
    assert {s.value for s in ExecutionStatus} == expected


def test_unknown_outcome_is_not_failed():
    """§5 — UNKNOWN_OUTCOME is distinct from FAILED (a side effect may
    already have happened)."""
    assert ExecutionStatus.UNKNOWN_OUTCOME != ExecutionStatus.FAILED
    assert ExecutionStatus.UNKNOWN_OUTCOME in TERMINAL_STATUSES


def test_terminal_statuses_cover_final_states():
    assert ExecutionStatus.SUCCEEDED in TERMINAL_STATUSES
    assert ExecutionStatus.FAILED in TERMINAL_STATUSES
    assert ExecutionStatus.TIMED_OUT in TERMINAL_STATUSES
    assert ExecutionStatus.CANCELLED in TERMINAL_STATUSES
    assert ExecutionStatus.REJECTED in TERMINAL_STATUSES
    assert ExecutionStatus.UNKNOWN_OUTCOME in TERMINAL_STATUSES
    assert ExecutionStatus.STARTED not in TERMINAL_STATUSES


def test_execution_request_roundtrip():
    """§3 — ExecutionRequest carries every mandatory field."""
    req = ExecutionRequest(
        request_id="r1", run_id="run1", step_id="s1",
        intent="status_read", intent_subtype="runtime",
        capability="STATUS_RUNTIME", tool_name="runtime_status",
        policy_version="cap-policy-v1", policy_decision_id="pd1",
        arguments={"scope": "runtime"}, timeout_ms=1500,
        idempotency_key="k1",
        expected_side_effect="READ_ONLY", expected_risk_class="READ_ONLY",
        operator_context={"user": "operator"},
        metadata={"goal": "status hermes"},
    )
    d = req.to_dict()
    assert d["request_id"] == "r1"
    assert d["run_id"] == "run1"
    assert d["step_id"] == "s1"
    assert d["capability"] == "STATUS_RUNTIME"
    assert d["tool_name"] == "runtime_status"
    assert d["policy_version"] == "cap-policy-v1"
    assert d["policy_decision_id"] == "pd1"
    assert d["timeout_ms"] == 1500
    assert d["idempotency_key"] == "k1"
    assert d["expected_side_effect"] == "READ_ONLY"
    assert d["expected_risk_class"] == "READ_ONLY"
    assert d["operator_context"] == {"user": "operator"}


def test_execution_result_ok_only_on_succeeded():
    res = ExecutionResult(
        execution_id="e1", request_id="r1", run_id="run1", step_id="s1",
        tool_name="runtime_status",
        status=ExecutionStatus.SUCCEEDED,
        started_at=datetime.now(timezone.utc),
    )
    assert res.ok is True
    res2 = ExecutionResult(
        execution_id="e2", request_id="r1", run_id="run1", step_id="s1",
        tool_name="runtime_status", status=ExecutionStatus.FAILED,
        started_at=datetime.now(timezone.utc),
    )
    assert res2.ok is False


def test_metadata_whitelist():
    """§3 — metadata is bounded/whitelisted."""
    assert is_metadata_allowed({"goal": "x", "channel": "telegram"})
    assert not is_metadata_allowed({"password": "hunter2"})
    assert not is_metadata_allowed({"anything": 1})


def test_side_effect_report_read_only_compatibility():
    """§34 — READ_ONLY descriptor accepts only NONE/READ_ONLY."""
    assert side_effect_report_compatible_with_read_only("NONE")
    assert side_effect_report_compatible_with_read_only("READ_ONLY")
    assert not side_effect_report_compatible_with_read_only("WRITE")
    assert not side_effect_report_compatible_with_read_only("SYSTEM")
    assert not side_effect_report_compatible_with_read_only("UNKNOWN")
    assert not side_effect_report_compatible_with_read_only("bogus")
