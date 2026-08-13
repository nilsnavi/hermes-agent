"""Pagination tests (Sprint 1.0.6.3 §54-56, MUST-HAVE 24)."""

from agent.operations_v2.run_inspector import RunInspector

from .conftest import run_completed, run_gated, seed_runs_bulk


def test_list_runs_default_and_max(ops_db):
    seed_runs_bulk(ops_db, 120)
    inspector = RunInspector(ops_db)
    default = inspector.list_runs()          # default 50
    assert len(default) == 50
    capped = inspector.list_runs(limit=10 ** 9)
    assert len(capped) <= 500
    assert len(inspector.list_runs(limit=500)) == 120  # fewer rows than cap


def test_timeline_cursor_pagination(ops_db, store, orchestrator):
    """§56 — before/after cursors page the journal without dumping it."""
    run_id = run_completed(orchestrator, store, "pg-run")
    inspector = RunInspector(ops_db)
    first = inspector.get_run_timeline(run_id, limit=3)
    assert len(first) == 3
    last_id = first[-1].event_id
    second = inspector.get_run_timeline(run_id, limit=3, after=last_id)
    assert second and second[0].event_id > last_id
    before = inspector.get_run_timeline(run_id, limit=3, before=first[-1].event_id)
    assert all(i.event_id < first[-1].event_id for i in before)
    # walking forward with after reaches the end
    cursor = None
    pages = 0
    while True:
        page = inspector.get_run_timeline(run_id, limit=3, after=cursor)
        if not page:
            break
        cursor = page[-1].event_id
        pages += 1
        assert pages < 50  # bounded loop
    full = inspector.get_run_timeline(run_id, limit=1000)
    assert pages * 3 >= len(full) - 3


def test_filters_combined(ops_db, store, orchestrator):
    run_completed(orchestrator, store, "pg-complete")
    gated, _ = run_gated(orchestrator, store, "pg-wait")
    inspector = RunInspector(ops_db)
    running = inspector.list_runs(status="running", task_type="internal", limit=10)
    assert [r.run_id for r in running] == [gated]
    empty = inspector.list_runs(status="completed", task_type="nope", limit=10)
    assert empty == []
