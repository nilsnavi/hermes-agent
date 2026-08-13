"""CanaryMetrics tests (Sprint 1.0.6.3 §11-14, MUST-HAVE 4-5, 25)."""

import sqlite3

from agent.operations_v2.metrics import CanaryMetrics

from .conftest import run_completed, run_gated, seed_runs_bulk


def _insert_run(ops_db, run_id, status, started="2026-08-10T10:00:00+00:00",
                completed="2026-08-10T10:00:05+00:00"):
    conn = sqlite3.connect(ops_db)
    try:
        conn.execute(
            "INSERT INTO agent_v2_runs (id, task_type, status, model_profile,"
            " created_at, started_at, completed_at, version, updated_at)"
            " VALUES (?,?,?,?,?,?,?,1,?)",
            (run_id, "internal", status, "BALANCED", started, started,
             completed if status == "completed" else None, started),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_event(ops_db, run_id, event_type, payload="{}", ts="2026-08-10T10:00:01+00:00"):
    conn = sqlite3.connect(ops_db)
    try:
        conn.execute(
            "INSERT INTO agent_v2_events (run_id, event_type, timestamp, payload_json)"
            " VALUES (?,?,?,?)",
            (run_id, event_type, ts, payload),
        )
        conn.commit()
    finally:
        conn.close()


def test_metrics_correct(ops_db, store, orchestrator):
    """MUST-HAVE 4 — counters match the seeded reality exactly."""
    run_completed(orchestrator, store, "m-ok")   # completed, 1 tool
    run_completed(orchestrator, store, "m-ok2")  # completed, 1 tool
    run_gated(orchestrator, store, "m-wait")     # running, 0 tools, 1 approval
    metrics = CanaryMetrics(ops_db).compute("all")
    assert metrics["runs_total"] == 3
    assert metrics["runs_completed"] == 2
    assert metrics["runs_waiting_approval"] == 1
    assert metrics["tool_calls_total"] == 2
    assert metrics["approval_pending"] == 1
    assert metrics["runs_incomplete"] == 1
    assert metrics["canary_success_rate"] == 100.0
    assert metrics["canary_success_denominator"] == 2


def test_success_rate_excludes_waiting_approval(ops_db, store, orchestrator):
    """§12 — the waiting-approval run is NOT in the success denominator."""
    run_completed(orchestrator, store, "s-ok")
    run_gated(orchestrator, store, "s-wait")
    metrics = CanaryMetrics(ops_db).compute("all")
    assert metrics["canary_success_denominator"] == 1
    assert metrics["canary_success_rate"] == 100.0
    assert metrics["runs_waiting_approval"] == 1


def test_intentional_failures_counted_honestly(ops_db, store, orchestrator):
    """MUST-HAVE 5 — deliberate failures are counted (not masked)."""
    _insert_run(ops_db, "f1", "failed")
    _insert_event(ops_db, "f1", "TOOL_FAILED", '{"step":"step-1","tool":"flaky_probe","error_class":"failure"}')
    _insert_run(ops_db, "f2", "failed")
    _insert_event(ops_db, "f2", "TOOL_FAILED", '{"step":"step-1","tool":"slow_probe","error_class":"timeout"}')
    _insert_event(ops_db, "f2", "ORCHESTRATION_STOPPED", '{"stop_reason":"max_failures"}')
    metrics = CanaryMetrics(ops_db).compute("all")
    assert metrics["runs_failed"] == 2
    assert metrics["tool_failures"] == 1  # failure class, timeout excluded
    assert metrics["tool_timeouts"] == 1
    assert metrics["canary_success_rate"] == 0.0
    assert metrics["error_taxonomy"]["TOOL_FAILED"] == 1
    assert metrics["error_taxonomy"]["TOOL_TIMEOUT"] == 1


def test_error_taxonomy_structured(ops_db):
    """§14 — errors aggregate by structured class, not free text."""
    _insert_run(ops_db, "e-invalid", "failed")
    _insert_event(ops_db, "e-invalid", "ORCHESTRATION_STOPPED",
                  '{"stop_reason":"invalid_plan"}')
    _insert_run(ops_db, "e-approval", "running")
    _insert_event(ops_db, "e-approval", "ORCHESTRATION_STOPPED",
                  '{"stop_reason":"approval_required"}')
    _insert_run(ops_db, "e-budget", "failed")
    _insert_event(ops_db, "e-budget", "BUDGET_EXCEEDED", '{"limit":"max_tool_calls"}')
    _insert_run(ops_db, "e-review", "running")
    _insert_event(ops_db, "e-review", "RECOVERY_MANUAL_REVIEW", '{"reason":"ambiguous"}')
    metrics = CanaryMetrics(ops_db).compute("all")
    taxonomy = metrics["error_taxonomy"]
    assert taxonomy["INVALID_PLAN"] == 1
    assert taxonomy["APPROVAL_REQUIRED"] == 1
    assert taxonomy["BUDGET_EXCEEDED"] >= 1
    assert taxonomy["MANUAL_REVIEW"] >= 1


def test_latency_percentiles_with_samples(ops_db):
    """§13 — p50/p95 with sample counts; empty sample → None, no fake stats."""
    _insert_run(ops_db, "l1", "completed",
                started="2026-08-10T10:00:00+00:00",
                completed="2026-08-10T10:00:01+00:00")  # 1000 ms
    _insert_run(ops_db, "l2", "completed",
                started="2026-08-10T10:00:00+00:00",
                completed="2026-08-10T10:00:02+00:00")  # 2000 ms
    metrics = CanaryMetrics(ops_db).compute("all")
    latency = metrics["latency_ms"]
    assert latency["run_duration_samples"] == 2
    assert latency["p50_run_duration"] == 1000.0
    assert latency["p95_run_duration"] == 2000.0
    # tool durations: none seeded → None, never fabricated
    assert latency["tool_duration_samples"] == 0
    assert latency["p50_tool_duration"] is None


def test_tool_duration_pairs(ops_db):
    """TOOL_STARTED→TOOL_COMPLETED pairing yields a real duration."""
    _insert_run(ops_db, "t1", "completed")
    _insert_event(ops_db, "t1", "TOOL_STARTED", '{"step":"step-1"}',
                  ts="2026-08-10T10:00:00+00:00")
    _insert_event(ops_db, "t1", "TOOL_COMPLETED", '{"step":"step-1"}',
                  ts="2026-08-10T10:00:00.500000+00:00")
    metrics = CanaryMetrics(ops_db).compute("all")
    latency = metrics["latency_ms"]
    assert latency["tool_duration_samples"] == 1
    assert latency["p50_tool_duration"] == 500.0


def test_duplicate_open_actions(ops_db):
    """§11 — TOOL_STARTED without completion/ failure → open action."""
    _insert_run(ops_db, "d1", "running")
    _insert_event(ops_db, "d1", "TOOL_STARTED", '{"step":"step-1"}')
    _insert_run(ops_db, "d2", "completed")
    _insert_event(ops_db, "d2", "TOOL_STARTED", '{"step":"step-1"}')
    _insert_event(ops_db, "d2", "TOOL_COMPLETED", '{"step":"step-1"}')
    metrics = CanaryMetrics(ops_db).compute("all")
    assert metrics["duplicate_action_detected"] == 1


def test_metric_windows(ops_db, store, orchestrator):
    """§53 — 1h/24h/all windows use timestamps."""
    run_completed(orchestrator, store, "w-now")  # created now (today)
    metrics_1h = CanaryMetrics(ops_db).compute("1h")
    metrics_all = CanaryMetrics(ops_db).compute("all")
    assert metrics_1h["runs_total"] >= 1
    assert metrics_all["runs_total"] == metrics_1h["runs_total"]
    try:
        CanaryMetrics(ops_db).compute("bogus")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_1000_runs_metrics_performant(ops_db):
    """MUST-HAVE 25 — 1000-run aggregation completes quickly."""
    seed_runs_bulk(ops_db, 1000)
    metrics = CanaryMetrics(ops_db).compute("all")
    assert metrics["runs_total"] == 1000
    assert metrics["runs_completed"] == 1000
    assert metrics["tool_calls_total"] == 1000
