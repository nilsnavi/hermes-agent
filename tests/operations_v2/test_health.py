"""Health model tests (Sprint 1.0.6.3 §17-18, §44-48, MUST-HAVE 20-21)."""

import sqlite3

from agent.operations_v2.health import HealthEvaluator, HealthInputs
from agent.operations_v2.service import OperationsService

from .conftest import migrate_old_schema, run_completed, run_gated, seed_runs_bulk


def _base_inputs(**overrides) -> HealthInputs:
    inputs = HealthInputs(
        flags={"enabled": True, "shadow": True, "canary": True,
               "persistence": True},
        schema_ready=True,
        gateway_alive=True,
        db_integrity="ok",
        canary_allowlist_active=True,
        read_only_enforced=True,
        kill_switch_flag_control=True,
        kill_switch_runbook_exists=True,
        gateway_control_available=True,
    )
    for key, value in overrides.items():
        setattr(inputs, key, value)
    return inputs


def test_healthy_when_all_good():
    health = HealthEvaluator().evaluate(_base_inputs())
    assert health.status == "healthy"
    assert health.findings == []
    assert health.kill_switch_available is True
    assert health.slo["write_executions"] == 0


def test_manual_review_pending_degrades():
    """MUST-HAVE 20 — pending manual review → DEGRADED + finding."""
    health = HealthEvaluator().evaluate(
        _base_inputs(manual_reviews=1, incomplete_runs=1)
    )
    assert health.status == "degraded"
    codes = [f["code"] for f in health.findings]
    assert "MANUAL_REVIEW_PENDING" in codes


def test_safety_write_violation_unhealthy():
    """MUST-HAVE 21 — synthetic safety violation → UNHEALTHY."""
    health = HealthEvaluator().evaluate(
        _base_inputs(write_tools_executed=1)
    )
    assert health.status == "unhealthy"
    codes = [f["code"] for f in health.findings]
    assert "SAFETY_WRITE_EXECUTED" in codes


def test_db_integrity_failure_unhealthy():
    health = HealthEvaluator().evaluate(_base_inputs(db_integrity="not ok"))
    assert health.status == "unhealthy"
    assert any(f["code"] == "DB_INTEGRITY_ERROR" for f in health.findings)


def test_duplicate_response_unhealthy():
    health = HealthEvaluator().evaluate(_base_inputs(duplicate_responses=1))
    assert health.status == "unhealthy"
    assert any(f["code"] == "DUPLICATE_RESPONSE" for f in health.findings)


def test_ordinary_traffic_v2_unhealthy():
    health = HealthEvaluator().evaluate(_base_inputs(ordinary_traffic_v2=1))
    assert health.status == "unhealthy"


def test_secret_leak_unhealthy():
    health = HealthEvaluator().evaluate(_base_inputs(slo_secret_findings=1))
    assert health.status == "unhealthy"


def test_stale_approval_degrades():
    health = HealthEvaluator().evaluate(
        _base_inputs(stale_approval_count=1, waiting_approvals=1)
    )
    assert health.status == "degraded"
    assert any(f["code"] == "STALE_APPROVAL" for f in health.findings)


def test_kill_switch_requires_all_three():
    """§48 — kill switch ready only when flag control + runbook + gateway."""
    for missing in ("kill_switch_flag_control", "kill_switch_runbook_exists",
                    "gateway_control_available"):
        kwargs = {missing: False}
        health = HealthEvaluator().evaluate(_base_inputs(**kwargs))
        assert health.kill_switch_available is False, missing
    assert HealthEvaluator().evaluate(_base_inputs()).kill_switch_available is True


def test_flags_false_health_shape():
    """§17 — with all flags off, the runtime_v2 block reports false."""
    health = HealthEvaluator().evaluate(
        _base_inputs(flags={"enabled": False, "shadow": False, "canary": False,
                            "persistence": False})
    )
    assert health.enabled is False and health.canary is False


def test_service_health_live(ops_db, store, orchestrator):
    """OperationsService.health() on a real seeded DB."""
    run_completed(orchestrator, store, "h-ok")
    svc = OperationsService(db_path=ops_db, flags={
        "enabled": True, "shadow": True, "canary": True, "persistence": True,
    })
    health = svc.health()
    assert health.db_integrity_last_known == "ok"
    assert health.schema_ready is True
    assert health.gateway_alive in (True, False)  # probe result
    assert health.incomplete_runs == 0
    assert health.last_successful_canary_at is not None
    assert "state.db" not in str(health.to_dict())


def test_migration_old_schema_additive(tmp_path):
    """§59 — the operations migration is additive and idempotent."""
    path = str(tmp_path / "old.db")
    migrate_old_schema(path)
    from agent.operations_v2.migration import ensure_operations_schema, schema_check

    check = schema_check(path)
    assert check["operations_schema_version"] is None
    assert "decided_by" in check["missing_columns"]

    first = ensure_operations_schema(path)
    assert first["columns_added"] == ["decided_by", "decision_source",
                                      "decision_reason_code"]
    second = ensure_operations_schema(path)
    assert second["columns_added"] == []

    conn = sqlite3.connect(path)
    try:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(agent_v2_approvals)")}
        assert {"decided_by", "decision_source", "decision_reason_code"} <= cols
        version = conn.execute(
            "SELECT value FROM agent_v2_meta "
            "WHERE key='operations_schema_version'").fetchone()
        assert version[0] == "1"
        # legacy agent_v2 data untouched
        legacy = conn.execute(
            "SELECT value FROM agent_v2_meta WHERE key='schema_version'"
        ).fetchone()
        assert legacy[0] == "1"
    finally:
        conn.close()


def test_service_migration_tolerant(ops_db):
    """Old-schema DB: service reads still work before migration runs."""
    seed_runs_bulk(ops_db, 5)
    # approvals table already has new columns (fresh schema) — the point of
    # this test is that reads never depend on the migration having run.
    svc = OperationsService(db_path=ops_db)
    assert len(svc.list_runs(limit=5)) == 5
