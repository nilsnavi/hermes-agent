"""RunInspector tests (Sprint 1.0.6.3 §7-9, MUST-HAVE 1-3, 24)."""

import sqlite3

from agent.operations_v2.run_inspector import RunInspector

from .conftest import run_completed, run_gated, seed_runs_bulk


def test_list_runs_bounded(ops_db, store, orchestrator, registry):
    """MUST-HAVE 1 — list runs is bounded by limit and never dumps all."""
    for i in range(7):
        run_completed(orchestrator, store, f"r{i}")
    inspector = RunInspector(ops_db)
    all_runs = inspector.list_runs(limit=500)
    assert len(all_runs) == 7
    limited = inspector.list_runs(limit=3)
    assert len(limited) == 3
    # newest first (ISO timestamps compare lexically)
    assert limited[0].created_at is not None
    assert limited[0].created_at >= (limited[-1].created_at or "")
    # limit is clamped to the hard max
    assert len(inspector.list_runs(limit=10 ** 6)) <= 500


def test_get_run_not_found(ops_db):
    inspector = RunInspector(ops_db)
    try:
        inspector.get_run("does-not-exist")
        assert False, "expected RunNotFound"
    except Exception as exc:
        assert "not found" in str(exc)


def test_run_summary_no_raw_payload(ops_db, store, orchestrator):
    """MUST-HAVE 2 — summary exposes counts/status only, never prompts,
    arguments or outputs."""
    run_id = run_completed(orchestrator, store, "r-safe")
    summary = RunInspector(ops_db).get_run(run_id)
    blob = str(summary.to_dict())
    assert "prompt" not in blob.lower()
    assert "arguments" not in blob
    assert "result" not in blob
    assert "goal" not in blob
    assert summary.tool_calls == 1
    assert summary.step_count == 1
    assert summary.completed_steps == 1
    assert summary.status == "completed"
    assert summary.duration_ms is not None


def test_timeline_ordered(ops_db, store, orchestrator):
    """MUST-HAVE 3 — timeline items come back in event-id ascending order."""
    run_id = run_completed(orchestrator, store, "r-order")
    items = RunInspector(ops_db).get_run_timeline(run_id, limit=1000)
    ids = [i.event_id for i in items]
    assert ids == sorted(ids)
    assert len(ids) > 4  # RUN_CREATED ... TOOL_COMPLETED ... ORCHESTRATION_STOPPED
    types = [i.event_type for i in items]
    assert "TOOL_STARTED" in types and "TOOL_COMPLETED" in types


def test_timeline_whitelist_no_raw(ops_db, store, orchestrator):
    """Timeline items surface hashes/scalars — never raw payload fields."""
    run_id = run_completed(orchestrator, store, "r-tl")
    items = RunInspector(ops_db).get_run_timeline(run_id, limit=1000)
    for item in items:
        blob = str(item.to_dict())
        assert "payload" not in blob
        assert "arguments" not in blob
    tool_items = [i for i in items if i.event_type == "TOOL_STARTED"]
    assert tool_items, "expected at least one TOOL_STARTED"
    assert tool_items[0].tool_name == "runtime_status"


def test_incomplete_runs_and_waiting(ops_db, store, orchestrator):
    """Incomplete runs include the approval-paused run; completed ones not."""
    done_id = run_completed(orchestrator, store, "r-done")
    gated, approval = run_gated(orchestrator, store, "r-wait")
    inspector = RunInspector(ops_db)
    incomplete = inspector.get_incomplete_runs()
    ids = {r.run_id for r in incomplete}
    assert gated in ids
    assert done_id not in ids
    waiting = inspector.get_waiting_approvals()
    assert any(a.approval_id == approval.id for a in waiting)
    # C5-style: waiting approval run classifies wait_for_approval
    summary = inspector.get_run(gated)
    assert summary.status == "running"


def test_list_runs_filters(ops_db, store, orchestrator):
    run_completed(orchestrator, store, "f-ok")
    gated, _ = run_gated(orchestrator, store, "f-wait")
    inspector = RunInspector(ops_db)
    completed = inspector.list_runs(status="completed", limit=500)
    assert all(r.status == "completed" for r in completed)
    running = inspector.list_runs(status="running", limit=500)
    assert any(r.run_id == gated for r in running)


def test_stale_run_detection(ops_db, store, orchestrator):
    """§44 — incomplete run with no recent activity → STALE_RUN."""
    gated, _ = run_gated(orchestrator, store, "r-stale")
    # backdate the run's journal so it looks abandoned
    conn = sqlite3.connect(ops_db)
    try:
        conn.execute(
            "UPDATE agent_v2_events SET timestamp='2026-08-10T10:00:00+00:00' "
            "WHERE run_id=?", (gated,))
        conn.commit()
    finally:
        conn.close()
    inspector = RunInspector(ops_db)
    stale = inspector.get_stale_runs(threshold_minutes=1)
    assert any(s.run_id == gated and s.stale_reason == "STALE_RUN"
               for s in stale)


def test_pagination_bounded_1000(ops_db):
    """MUST-HAVE 24 — 1000 seeded runs list fast and bounded."""
    seed_runs_bulk(ops_db, 1000)
    inspector = RunInspector(ops_db)
    page = inspector.list_runs(limit=50)
    assert len(page) == 50
    assert inspector.list_runs(limit=500)  # hard cap works
