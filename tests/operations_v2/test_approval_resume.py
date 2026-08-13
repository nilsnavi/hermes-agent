"""Approval → resume tests (Sprint 1.0.6.3 §34-36, MUST-HAVE 13)."""

import sqlite3

from agent.operations_v2.approval_service import ApprovalService
from agent.operations_v2.models import OperatorIdentity
from agent.operations_v2.service import OperationsService

from .conftest import run_gated

OPERATOR = OperatorIdentity(operator_id="op-drill", source="cli",
                            roles=frozenset({"operator"}), authenticated=True)


def _side_effect(tool):
    return "read_only"


def _tool_event_counts(db_path, run_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        started = conn.execute(
            "SELECT COUNT(*) FROM agent_v2_events WHERE run_id=? AND "
            "event_type='TOOL_STARTED'", (run_id,)).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM agent_v2_events WHERE run_id=? AND "
            "event_type='TOOL_COMPLETED'", (run_id,)).fetchone()[0]
        return started, completed
    finally:
        conn.close()


def test_approve_then_resume_exactly_once(ops_db, store, orchestrator):
    """MUST-HAVE 13 — approve → resume → COMPLETED, exactly one tool call."""
    run_id, approval = run_gated(orchestrator, store, "ap-resume")
    svc = OperationsService(db_path=ops_db, side_effect_fn=_side_effect)
    assert svc.get_run(run_id).status == "running"

    decision = svc.approve(approval.run_id, approval.id, OPERATOR)
    assert decision.decision == "approved"

    result = svc.resume(run_id)
    assert result["status"] == "completed", result
    assert result["tool_calls"] == 1
    started, completed = _tool_event_counts(ops_db, run_id)
    assert started == 1 and completed == 1  # exactly once

    # a second resume is refused (terminal run)
    again = svc.resume(run_id)
    assert again["tool_calls"] == 1  # no duplicate tool call


def test_reject_then_no_tool_execution(ops_db, store, orchestrator):
    """§36 — reject → resume performs ZERO tool calls (terminal per policy)."""
    run_id, approval = run_gated(orchestrator, store, "ap-rej2")
    svc = OperationsService(db_path=ops_db, side_effect_fn=_side_effect)
    svc.reject(approval.run_id, approval.id, OPERATOR)
    result = svc.resume(run_id)
    assert result["tool_calls"] == 0
    started, completed = _tool_event_counts(ops_db, run_id)
    assert started == 0 and completed == 0


def test_approval_timeline_coherent_after_resume(ops_db, store, orchestrator):
    """§35 — after approve+resume the journal is coherent (no gap/dup)."""
    run_id, approval = run_gated(orchestrator, store, "ap-coherent")
    svc = OperationsService(db_path=ops_db, side_effect_fn=_side_effect)
    svc.approve(approval.run_id, approval.id, OPERATOR)
    svc.resume(run_id)
    items = svc.timeline(run_id, limit=1000)
    types = [i.event_type for i in items]
    assert types.count("STEP_WAITING_APPROVAL") == 1
    assert types.count("STEP_APPROVED") == 1
    assert types.count("TOOL_STARTED") == 1
    assert types.count("TOOL_COMPLETED") == 1
    assert types[-1] in ("ORCHESTRATION_STOPPED", "RUN_COMPLETED")
