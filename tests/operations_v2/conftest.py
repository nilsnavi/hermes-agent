"""Shared fixtures for operations_v2 tests (Sprint 1.0.6.3)."""

import os
import sqlite3

import pytest

from agent.execution.registry import SideEffectClass, ToolMetadata, ToolRegistry
from agent.gateway_v2.canary import default_canary_registry
from agent.orchestrator import RuntimeOrchestrator
from agent.persistence import SQLiteExecutionStore
from agent.persistence.schema import ensure_execution_schema
from agent.runtime.context import TaskContext

from agent.operations_v2.migration import ensure_operations_schema


@pytest.fixture
def ops_db(tmp_path):
    """Fresh DB with the FULL v2 schema (incl. approval decision columns)."""
    path = str(tmp_path / "ops.db")
    conn = sqlite3.connect(path)
    try:
        ensure_execution_schema(conn)
    finally:
        conn.close()
    return path


@pytest.fixture
def store(ops_db):
    s = SQLiteExecutionStore(ops_db)
    yield s
    s.close()


@pytest.fixture
def registry():
    return default_canary_registry()


@pytest.fixture
def orchestrator(store, registry):
    return RuntimeOrchestrator(store, registry)


def make_context(goal="test goal", risk="low", task_type="internal"):
    return TaskContext(
        goal=goal, allowed_tools=["runtime_status", "canary_ping"],
        risk_level=risk,
        metadata={"task_type": task_type},
    )


def run_completed(orchestrator, store, label=None, tool="runtime_status"):
    """Drive one read-only run to COMPLETED through the real path.

    Returns the ACTUAL generated run_id (the orchestrator owns the id).
    """
    ctx = make_context(goal=f"read {tool}", risk="low")
    result = orchestrator.run(
        ctx, step_specs=[{"name": "s1", "tool": tool}]
    )
    assert result.status == "completed", result
    return result.run_id


def run_gated(orchestrator, store, label=None, tool="runtime_status"):
    """Drive one run that pauses at the approval gate (critical risk).

    Returns (run_id, ApprovalRequest) of the staged approval.
    """
    ctx = make_context(goal=f"critical read {tool}", risk="critical")
    result = orchestrator.run(
        ctx, step_specs=[{"name": "s1", "tool": tool}]
    )
    assert result.stop_reason is not None
    assert result.stop_reason.value == "approval_required"
    approvals = store.list_approvals(run_id=result.run_id)
    assert len(approvals) == 1
    return result.run_id, approvals[0]


def seed_runs_bulk(db_path, n, per_run_steps=1, complete=True):
    """Bulk-seed n runs with steps + tool events (direct SQL, fast).

    Used ONLY for the 1000-run performance test — the observability
    layer is a pure reader, so hand-built rows are equivalent input.
    """
    conn = sqlite3.connect(db_path)
    try:
        base = "2026-08-10T10:00:00.000000+00:00"
        for i in range(n):
            run_id = f"run_seed_{i:05d}"
            status = "completed" if complete else "running"
            conn.execute(
                "INSERT INTO agent_v2_runs (id, task_type, status, model_profile,"
                " created_at, started_at, completed_at, version, updated_at)"
                " VALUES (?,?,?,?,?,?,?,1,?)",
                (run_id, "internal", status, "BALANCED", base, base,
                 base if complete else None, base),
            )
            plan_id = f"plan_seed_{i:05d}"
            conn.execute(
                "INSERT INTO agent_v2_plans (id, run_id, goal, status, created_at,"
                " version, updated_at) VALUES (?,?,?,?,?,1,?)",
                (plan_id, run_id, "seed", "created" if complete else "running",
                 base, base),
            )
            for s in range(per_run_steps):
                step_id = f"step-{s + 1}"
                step_status = "completed" if complete else "pending"
                conn.execute(
                    "INSERT INTO agent_v2_steps (id, plan_id, run_id, sequence, name,"
                    " description, tool, requires_approval, status, version, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,0,?,1,?)",
                    (step_id, plan_id, run_id, s + 1, f"s{s + 1}", "", "runtime_status",
                     step_status, base),
                )
            conn.execute(
                "INSERT INTO agent_v2_events (run_id, step_id, event_type, timestamp,"
                " payload_json) VALUES (?,?,?,?,?)",
                (run_id, "step-1", "TOOL_STARTED", base, '{"step":"step-1"}'),
            )
            conn.execute(
                "INSERT INTO agent_v2_events (run_id, step_id, event_type, timestamp,"
                " payload_json) VALUES (?,?,?,?,?)",
                (run_id, "step-1", "TOOL_COMPLETED", base, '{"step":"step-1"}'),
            )
        conn.commit()
    finally:
        conn.close()


def migrate_old_schema(path):
    """Build a DB with the PRE-1.0.6.3 approvals schema (no decision cols)."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE agent_v2_runs (
                id TEXT PRIMARY KEY, task_type TEXT NOT NULL, status TEXT NOT NULL,
                model_profile TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT,
                completed_at TEXT, error TEXT, result_json TEXT, context_json TEXT,
                version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
            CREATE TABLE agent_v2_plans (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, goal TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT, started_at TEXT, completed_at TEXT,
                metadata_json TEXT, version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
            CREATE TABLE agent_v2_steps (
                id TEXT NOT NULL, plan_id TEXT NOT NULL, run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                tool TEXT NOT NULL, arguments_json TEXT, requires_approval INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL, result_json TEXT, error TEXT, created_at TEXT,
                started_at TEXT, completed_at TEXT, updated_at TEXT, version INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (plan_id, id));
            CREATE TABLE agent_v2_approvals (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, created_at TEXT,
                expires_at TEXT, decided_at TEXT, decision_reason TEXT,
                version INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL);
            CREATE TABLE agent_v2_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, step_id TEXT,
                event_type TEXT NOT NULL, timestamp TEXT NOT NULL, payload_json TEXT,
                input_hash TEXT, output_hash TEXT);
            CREATE TABLE agent_v2_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO agent_v2_meta(key, value) VALUES ('schema_version', '1');
            """
        )
        conn.commit()
    finally:
        conn.close()
