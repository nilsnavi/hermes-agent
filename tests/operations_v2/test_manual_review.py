"""Manual review reconstruction tests (Sprint 1.0.6.3 §41-43, MUST-HAVE 18)."""

import sqlite3

from agent.operations_v2.manual_review import ManualReviewOps

from .conftest import run_completed, run_gated, seed_runs_bulk


def _inject_recovery_manual_review(db_path, run_id, reason="ambiguous tool"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO agent_v2_events (run_id, event_type, timestamp, payload_json)"
            " VALUES (?, 'RECOVERY_MANUAL_REVIEW',"
            " '2026-08-10T10:00:00+00:00', ?)",
            (run_id, '{"reason":"%s"}' % reason),
        )
        conn.commit()
    finally:
        conn.close()


def test_reconstructed_from_durable_state(ops_db, store, orchestrator):
    """MUST-HAVE 18 — manual reviews rebuild from the journal (no memory)."""
    run_completed(orchestrator, store, "mr-done")
    gated, _ = run_gated(orchestrator, store, "mr-wait")
    _inject_recovery_manual_review(ops_db, gated)
    items = ManualReviewOps(ops_db).list_pending()
    assert any(i.run_id == gated for i in items)
    item = next(i for i in items if i.run_id == gated)
    assert item.recovery_disposition == "manual_review"
    assert item.created_at is not None
    assert item.recommended_actions
    assert "timeline" in item.recommended_actions[0].lower()


def test_reconstructed_after_reopen(ops_db, store, orchestrator):
    """Restart-proof: a NEW ManualReviewOps instance sees the same list."""
    run_completed(orchestrator, store, "mr-ok")
    gated, _ = run_gated(orchestrator, store, "mr-again")
    _inject_recovery_manual_review(ops_db, gated)
    first = ManualReviewOps(ops_db).list_pending()
    second = ManualReviewOps(ops_db).list_pending()  # fresh instance = restart
    assert [i.run_id for i in first] == [i.run_id for i in second]
    assert len(first) == 1


def test_open_tool_attempt_detected(ops_db, store, orchestrator):
    """An incomplete run with TOOL_STARTED but no completion is flagged."""
    gated, _ = run_gated(orchestrator, store, "mr-open")
    conn = sqlite3.connect(ops_db)
    try:
        conn.execute(
            "INSERT INTO agent_v2_events (run_id, step_id, event_type, timestamp,"
            " payload_json) VALUES (?, 'step-1', 'TOOL_STARTED',"
            " '2026-08-10T10:00:00+00:00', '{\"step\":\"step-1\",\"tool\":\"search\"}')",
            (gated,),
        )
        conn.commit()
    finally:
        conn.close()
    items = ManualReviewOps(ops_db).list_pending()
    item = next((i for i in items if i.run_id == gated), None)
    assert item is not None
    assert item.step_id == "step-1"
    assert "ambiguous" in item.reason.lower()


def test_no_review_items_when_clean(ops_db, store, orchestrator):
    run_completed(orchestrator, store, "mr-clean")
    assert ManualReviewOps(ops_db).list_pending() == []


def test_no_raw_payload_in_items(ops_db, store, orchestrator):
    gated, _ = run_gated(orchestrator, store, "mr-safe")
    _inject_recovery_manual_review(ops_db, gated)
    items = ManualReviewOps(ops_db).list_pending()
    for item in items:
        blob = str(item.to_dict())
        assert "prompt" not in blob.lower()
        assert "arguments" not in blob
        assert "token" not in blob.lower() or "token_count" in blob
