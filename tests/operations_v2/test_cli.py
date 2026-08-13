"""Operations CLI tests (Sprint 1.0.6.3 §20, §38-40, MUST-HAVE 23)."""

import json
import os
import subprocess
import sys

import pytest

from agent.operations_v2.cli import main

from .conftest import run_completed, run_gated

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VENV_PY = os.path.join(REPO, "venv", "bin", "python")


def _run_cli(args, db):
    return subprocess.run(
        [VENV_PY, "-m", "agent.operations_v2.cli", *args, "--db", db],
        capture_output=True, text=True, timeout=60,
    )


def _run_inproc(args, db):
    """In-process invocation (argparse) — for fast unit checks."""
    from agent.operations_v2 import cli

    old = sys.argv
    try:
        return main([*args, "--db", db])
    finally:
        sys.argv = old


def test_cli_runs_readonly(ops_db, store, orchestrator):
    run_id = run_completed(orchestrator, store, "cli-ok")
    proc = _run_cli(["runs", "--limit", "10"], ops_db)
    assert proc.returncode == 0
    assert run_id in proc.stdout


def test_cli_json_stable(ops_db, store, orchestrator):
    """MUST-HAVE 23 — --json output parses with a stable schema."""
    run_id = run_completed(orchestrator, store, "cli-json")
    proc = _run_cli(["run", run_id, "--json"], ops_db)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["run_id"] == run_id
    assert data["status"] == "completed"
    assert set(data) >= {"run_id", "status", "task_type", "duration_ms",
                         "tool_calls", "approval_count", "stop_reason"}


def test_cli_health_no_secrets(ops_db, store, orchestrator):
    run_completed(orchestrator, store, "cli-h")
    proc = _run_cli(["health", "--json"], ops_db)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "status" in data
    assert "state.db" not in proc.stdout
    assert "token" not in proc.stdout.lower()


def test_cli_timeline(ops_db, store, orchestrator):
    run_id = run_completed(orchestrator, store, "cli-tl")
    proc = _run_cli(["timeline", run_id, "--json"], ops_db)
    data = json.loads(proc.stdout)
    assert isinstance(data, list) and len(data) > 0
    assert data[0]["event_type"] == "RUN_CREATED"
    ids = [i["event_id"] for i in data]
    assert ids == sorted(ids)


def test_cli_approvals_pending(ops_db, store, orchestrator):
    _, approval = run_gated(orchestrator, store, "cli-ap")
    proc = _run_cli(["approvals", "--json"], ops_db)
    data = json.loads(proc.stdout)
    assert any(a["approval_id"] == approval.id for a in data)


def test_cli_approve_requires_confirm_and_operator(ops_db, store, orchestrator):
    """§38 — mutation commands need --operator AND --confirm; no Enter-approve."""
    _, approval = run_gated(orchestrator, store, "cli-confirm")
    proc = _run_cli(["approve", approval.id, "--run-id", approval.run_id], ops_db)
    assert proc.returncode != 0
    assert "confirm" in proc.stderr.lower() or "operator" in proc.stderr.lower()
    proc = _run_cli(
        ["approve", approval.id, "--run-id", approval.run_id,
         "--operator", "op-1"], ops_db)
    assert proc.returncode != 0  # still missing --confirm
    proc = _run_cli(
        ["approve", approval.id, "--run-id", approval.run_id,
         "--operator", "op-1", "--confirm", "--json"], ops_db)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["decision"] == "approved"
    assert data["decided_by"] == "op-1"


def test_cli_approve_dry_run_zero_writes(ops_db, store, orchestrator):
    """§39 — --dry-run shows the transition and writes nothing."""
    _, approval = run_gated(orchestrator, store, "cli-dry")
    proc = _run_cli(
        ["approve", approval.id, "--run-id", approval.run_id,
         "--operator", "op-1", "--dry-run", "--json"], ops_db)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["expected_transition"] == "pending -> approved"
    assert data["writes"] == 0
    import sqlite3
    conn = sqlite3.connect(ops_db)
    try:
        status = conn.execute(
            "SELECT status FROM agent_v2_approvals WHERE id=?",
            (approval.id,)).fetchone()[0]
    finally:
        conn.close()
    assert status == "pending"


def test_cli_metrics_and_stale(ops_db, store, orchestrator):
    run_completed(orchestrator, store, "cli-m")
    proc = _run_cli(["metrics", "--window", "all", "--json"], ops_db)
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["runs_completed"] >= 1
    proc = _run_cli(["stale-runs", "--threshold-min", "1", "--json"], ops_db)
    assert proc.returncode == 0
    assert isinstance(json.loads(proc.stdout), list)


def test_cli_reject_no_execution(ops_db, store, orchestrator):
    _, approval = run_gated(orchestrator, store, "cli-rej")
    proc = _run_cli(
        ["reject", approval.id, "--run-id", approval.run_id,
         "--operator", "op-1", "--confirm", "--json"], ops_db)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["decision"] == "rejected"


def test_cli_manual_reviews(ops_db, store, orchestrator):
    run_completed(orchestrator, store, "cli-mr")
    proc = _run_cli(["manual-reviews", "--json"], ops_db)
    assert proc.returncode == 0
    assert isinstance(json.loads(proc.stdout), list)


def test_cli_schema_commands(ops_db):
    proc = _run_cli(["schema-check"], ops_db)
    assert proc.returncode == 0
    check = json.loads(proc.stdout)
    assert check["missing_columns"] == []
    proc = _run_cli(["schema-apply"], ops_db)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["columns_added"] == []
