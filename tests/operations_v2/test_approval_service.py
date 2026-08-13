"""ApprovalService tests (Sprint 1.0.6.3 §22-33, §40, MUST-HAVE 6-7, 15-17, 22)."""

import sqlite3

import pytest

from agent.operations_v2.approval_service import ApprovalService
from agent.operations_v2.exceptions import (
    ApprovalAlreadyDecidedError,
    ApprovalScopeMismatch,
    PolicyDeniedError,
    RunTerminalError,
    StaleVersionError,
    UnauthorizedOperator,
)
from agent.operations_v2.models import OperatorIdentity
from agent.operations_v2.service import OperationsService

from .conftest import run_completed, run_gated

OPERATOR = OperatorIdentity(operator_id="op-1", source="cli",
                            roles=frozenset({"operator"}), authenticated=True)
UNAUTH = OperatorIdentity(operator_id="op-1", source="cli", authenticated=False)


def _side_effect(tool):
    return "read_only" if tool in ("runtime_status", "canary_ping") else None


def _service(db_path):
    return ApprovalService(db_path, tool_side_effect_fn=_side_effect)


def _approval_row(db_path, approval_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM agent_v2_approvals WHERE id=?", (approval_id,)
        ).fetchone()
    finally:
        conn.close()


def _events_for(db_path, run_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT event_type, payload_json FROM agent_v2_events "
            "WHERE run_id=? ORDER BY id", (run_id,))]
    finally:
        conn.close()


def test_pending_approvals_listed(ops_db, store, orchestrator):
    """MUST-HAVE 6 — pending approval is visible to the operator."""
    _, approval = run_gated(orchestrator, store, "ap-wait")
    pending = _service(ops_db).list_pending()
    assert any(a.approval_id == approval.id for a in pending)


def test_approve_atomic(ops_db, store, orchestrator):
    """MUST-HAVE 7 — approve = approval APPROVED + step READY + event, one tx."""
    _, approval = run_gated(orchestrator, store, "ap-ok")
    decision = _service(ops_db).approve(
        approval.run_id, approval.id, OPERATOR
    )
    assert decision.decision == "approved"
    row = _approval_row(ops_db, approval.id)
    assert row["status"] == "approved"
    assert row["decided_by"] == "op-1"
    assert row["decision_source"] == "cli"
    assert row["decision_reason_code"] == "operator_approved"
    assert row["decided_at"] is not None
    # step flipped to READY
    step = store.get_step(f"plan-{approval.run_id}", approval.step_id)
    assert step.status.value == "ready"
    # audit event persisted
    events = _events_for(ops_db, approval.run_id)
    assert any(e["event_type"] == "APPROVAL_APPROVED" for e in events)
    assert "operator" in events[-1]["payload_json"]


def test_operator_identity_required(ops_db, store, orchestrator):
    """MUST-HAVE 15-16 — unauthenticated operator → DENY."""
    _, approval = run_gated(orchestrator, store, "ap-deny")
    with pytest.raises(UnauthorizedOperator):
        _service(ops_db).approve(approval.run_id, approval.id, UNAUTH)
    with pytest.raises(UnauthorizedOperator):
        _service(ops_db).approve(approval.run_id, approval.id, None)  # type: ignore[arg-type]
    # nothing mutated
    assert _approval_row(ops_db, approval.id)["status"] == "pending"


def test_approve_run_scoped(ops_db, store, orchestrator):
    """§23 — approval must belong to the run (scope check)."""
    _, approval = run_gated(orchestrator, store, "ap-scope")
    other_id = run_completed(orchestrator, store, "ap-other")
    with pytest.raises(ApprovalScopeMismatch):
        _service(ops_db).approve(other_id, approval.id, OPERATOR)


def test_write_risk_approval_denied(ops_db, store, orchestrator):
    """MUST-HAVE 17 — write-risk approval still denied (policy, not operator)."""
    _, approval = run_gated(orchestrator, store, "ap-write")
    # same approval, but the side-effect lookup now says it is not read-only
    svc = ApprovalService(ops_db, tool_side_effect_fn=lambda tool: "irreversible_write")
    with pytest.raises(PolicyDeniedError):
        svc.approve(approval.run_id, approval.id, OPERATOR)
    assert _approval_row(ops_db, approval.id)["status"] == "pending"


def test_stale_version_blocked(ops_db, store, orchestrator):
    """MUST-HAVE 9 — version mismatch → blocked, no overwrite."""
    _, approval = run_gated(orchestrator, store, "ap-ver")
    with pytest.raises(StaleVersionError):
        _service(ops_db).approve(approval.run_id, approval.id, OPERATOR,
                                 expected_version=99)
    assert _approval_row(ops_db, approval.id)["status"] == "pending"


def test_approve_cancelled_blocked(ops_db, store, orchestrator):
    """MUST-HAVE 10 — cancelled run → approve DENY (no revival)."""
    _, approval = run_gated(orchestrator, store, "ap-cancel")
    result = orchestrator.cancel(approval.run_id)
    assert result.status == "cancelled"
    with pytest.raises(RunTerminalError):
        _service(ops_db).approve(approval.run_id, approval.id, OPERATOR)
    assert _approval_row(ops_db, approval.id)["status"] == "pending"


def test_approval_output_safety(ops_db, store, orchestrator):
    """§40 — approval views never carry prompts/arguments/secret payloads."""
    _, approval = run_gated(orchestrator, store, "ap-safe")
    view = _service(ops_db).get(approval.id, run_id=approval.run_id)
    blob = str(view.to_dict())
    assert "prompt" not in blob.lower()
    assert "arguments" not in blob
    assert "secret" not in blob.lower()
    assert view.tool == "runtime_status"
    assert view.task_type == "internal"


def test_reject_no_tool_execution(ops_db, store, orchestrator):
    """MUST-HAVE 12 — reject: approval REJECTED, step SKIPPED, 0 tools."""
    _, approval = run_gated(orchestrator, store, "ap-rej")
    decision = _service(ops_db).reject(approval.run_id, approval.id, OPERATOR)
    assert decision.decision == "rejected"
    row = _approval_row(ops_db, approval.id)
    assert row["status"] == "rejected"
    assert row["decision_reason_code"] == "operator_rejected"
    step = store.get_step(f"plan-{approval.run_id}", approval.step_id)
    assert step.status.value == "skipped"
    events = _events_for(ops_db, approval.run_id)
    assert any(e["event_type"] == "APPROVAL_REJECTED" for e in events)
    # no tool ever started
    assert not any(e["event_type"] == "TOOL_STARTED" for e in events)


def test_dry_run_zero_writes(ops_db, store, orchestrator):
    """§39 — dry-run shows the planned transition, ZERO writes."""
    _, approval = run_gated(orchestrator, store, "ap-dry")
    svc = _service(ops_db)
    report = svc.dry_run(approval.run_id, approval.id, OPERATOR, "approve")
    assert report["policy_result"]["allowed"] is True
    assert report["expected_transition"] == "pending -> approved"
    assert report["writes"] == 0
    assert _approval_row(ops_db, approval.id)["status"] == "pending"


def test_decision_metadata_durable_after_reopen(ops_db, store, orchestrator):
    """§26/51 — decision metadata survives a store reopen (durable)."""
    _, approval = run_gated(orchestrator, store, "ap-durable")
    _service(ops_db).approve(approval.run_id, approval.id, OPERATOR,
                             note="read-only status check")
    view = _service(ops_db).get(approval.id, run_id=approval.run_id)
    assert view.decided_by == "op-1"
    assert view.decision_reason_code == "operator_approved"
    assert view.status == "approved"
    assert view.version == 2


def test_approval_viewed_event_optional(ops_db, store, orchestrator):
    """§51 — APPROVAL_VIEWED is optional and audit-safe when recorded."""
    _, approval = run_gated(orchestrator, store, "ap-view")
    svc = ApprovalService(ops_db, tool_side_effect_fn=_side_effect)
    # default: no view event
    svc.get(approval.id)
    events = _events_for(ops_db, approval.run_id)
    assert not any(e["event_type"] == "APPROVAL_VIEWED" for e in events)


def test_service_facade_approve(ops_db, store, orchestrator):
    """OperationsService.approve wires the same policy."""
    _, approval = run_gated(orchestrator, store, "ap-facade")
    svc = OperationsService(db_path=ops_db, side_effect_fn=_side_effect)
    decision = svc.approve(approval.run_id, approval.id, OPERATOR)
    assert decision.decision == "approved"
    assert svc.get_approval(approval.id).status == "approved"
