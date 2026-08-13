"""SQLite execution store (Sprint 1.0.3) — durable persistence backend.

Implements the ExecutionStore contract (same surface as
``agent.execution.executor.MemoryExecutionStore``) plus persistence
extensions. Design rules:

- ONE connection per store instance (thread-safe via a lock), busy_timeout,
  foreign_keys=ON. No per-field connections.
- Short transactions only — the engine NEVER holds a write transaction
  across an external tool call (see ExecutionEngine).
- Optimistic concurrency: every update is ``UPDATE ... WHERE id=? AND
  version=?``; a stale write raises ConcurrentUpdateError.
- Sensitive payloads are scrubbed at the write boundary (redaction.scrub)
  — plaintext credentials never reach the DB.
- Event journal is append-only by API design: no UPDATE of event rows.
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from agent.execution.approval import ApprovalRequest, ApprovalStatus
from agent.execution.exceptions import ConcurrentUpdateError, ExecutionErrorBase
from agent.execution.models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from agent.runtime.events import RuntimeEvent
from agent.runtime.models import AgentRun
from agent.runtime.states import RunStatus

from . import redaction, schema
from .serialization import dumps, isoformat, loads, parse_timestamp


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteExecutionStore:
    """Durable store for runs / plans / steps / approvals / events.

    Contract (must mirror MemoryExecutionStore):
      save_plan, save_step, get_plan, update_step, get_step, list_plans
    Extensions:
      save_run, get_run, update_run, list_incomplete_runs,
      save_approval, get_approval, update_approval, list_approvals,
      append_event, list_events,
      transaction()  (atomic multi-write boundary)
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False

    # ── connection policy ────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        # check_same_thread=False: the store's RLock serializes ALL access,
        # so a cooperative cancel() from a tool's worker thread is safe.
        conn = sqlite3.connect(self._path, timeout=10.0,
                               isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _acquire(self) -> sqlite3.Connection:
        with self._lock:
            if self._closed:
                raise ExecutionErrorBase("store is closed")
            if self._conn is None:
                self._conn = self._connect()
                schema.ensure_execution_schema(self._conn)
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            self._closed = True

    def __enter__(self) -> "SQLiteExecutionStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """One atomic write boundary (BEGIN IMMEDIATE ... COMMIT/ROLLBACK).

        The engine groups related writes (step status + approval + event)
        inside a single ``with store.transaction():`` block.
        """
        conn = self._acquire()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    # ── runs ─────────────────────────────────────────────────────────

    def save_run(self, run: AgentRun) -> None:
        """Idempotent create/update (safe on retry — never version-guarded)."""
        data = run.to_dict()
        with self._lock:
            conn = self._acquire()
            conn.execute(
                f"""
                INSERT INTO {schema.RUNS} (
                    id, task_type, status, model_profile, created_at,
                    started_at, completed_at, error, result_json, context_json,
                    version, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status, model_profile=excluded.model_profile,
                    started_at=excluded.started_at, completed_at=excluded.completed_at,
                    error=excluded.error, result_json=excluded.result_json,
                    context_json=excluded.context_json, updated_at=excluded.updated_at
                """,
                (
                    data["id"], data["task_type"], data["status"], data["model_profile"],
                    data["created_at"], data["started_at"], data["completed_at"],
                    data["error"], dumps(redaction.scrub(data.get("result"))),
                    dumps(redaction.scrub(data.get("context"))),
                    1, _now(),
                ),
            )

    def get_run(self, run_id: str) -> AgentRun:
        with self._lock:
            row = self._acquire().execute(
                f"SELECT * FROM {schema.RUNS} WHERE id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise ExecutionErrorBase(f"run not found: {run_id}")
        return self._run_from_row(row)

    def update_run(self, run: AgentRun, expected_version: Optional[int] = None) -> None:
        """Version-guarded update — raises ConcurrentUpdateError on conflict.

        *expected_version* is the version the caller observed (strict
        optimistic concurrency); None re-reads it (engine convenience path).
        """
        data = run.to_dict()
        with self._lock:
            conn = self._acquire()
            row = conn.execute(
                f"SELECT version FROM {schema.RUNS} WHERE id=?", (run.id,)
            ).fetchone()
            if row is None:
                raise ExecutionErrorBase(f"run not found: {run.id}")
            base = row["version"] if expected_version is None else expected_version
            cur = conn.execute(
                f"""
                UPDATE {schema.RUNS} SET
                    status=?, model_profile=?, started_at=?, completed_at=?,
                    error=?, result_json=?, context_json=?, version=?, updated_at=?
                WHERE id=? AND version=?
                """,
                (
                    data["status"], data["model_profile"], data["started_at"],
                    data["completed_at"], data["error"],
                    dumps(redaction.scrub(data.get("result"))),
                    dumps(redaction.scrub(data.get("context"))),
                    base + 1, _now(), run.id, base,
                ),
            )
            if cur.rowcount == 0:
                raise ConcurrentUpdateError(schema.RUNS, run.id)

    def list_incomplete_runs(self) -> List[AgentRun]:
        """Runs in any non-terminal state (recovery candidates)."""
        with self._lock:
            rows = self._acquire().execute(
                f"SELECT * FROM {schema.RUNS} WHERE status NOT IN (?,?,?)",
                (RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value),
            ).fetchall()
        return [self._run_from_row(r) for r in rows]

    def _run_from_row(self, row: sqlite3.Row) -> AgentRun:
        return AgentRun(
            id=row["id"],
            task_type=row["task_type"],
            status=RunStatus(row["status"]),
            model_profile=row["model_profile"],
            created_at=parse_timestamp(row["created_at"]) or datetime.now(timezone.utc),
            started_at=parse_timestamp(row["started_at"]),
            completed_at=parse_timestamp(row["completed_at"]),
            error=row["error"],
            result=loads(row["result_json"]),
            context=loads(row["context_json"]),
        )

    # ── plans ────────────────────────────────────────────────────────

    def save_plan(self, plan: ExecutionPlan) -> None:
        data = plan.to_dict()
        with self._lock:
            conn = self._acquire()
            conn.execute(
                f"""
                INSERT INTO {schema.PLANS} (
                    id, run_id, goal, status, created_at, started_at,
                    completed_at, metadata_json, version, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    run_id=excluded.run_id, goal=excluded.goal, status=excluded.status,
                    started_at=excluded.started_at, completed_at=excluded.completed_at,
                    metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
                """,
                (
                    data["id"], data["run_id"], data["goal"], data["status"],
                    data["created_at"], data["started_at"], data["completed_at"],
                    dumps(redaction.scrub(data.get("metadata"))), 1, _now(),
                ),
            )

    def get_plan(self, plan_id: str) -> ExecutionPlan:
        with self._lock:
            row = self._acquire().execute(
                f"SELECT * FROM {schema.PLANS} WHERE id=?", (plan_id,)
            ).fetchone()
        if row is None:
            raise ExecutionErrorBase(f"plan not found: {plan_id}")
        plan = ExecutionPlan(
            id=row["id"],
            run_id=row["run_id"],
            goal=row["goal"],
            steps=self.list_steps(plan_id),
            status=PlanStatus(row["status"]),
            created_at=parse_timestamp(row["created_at"]),
            started_at=parse_timestamp(row["started_at"]),
            completed_at=parse_timestamp(row["completed_at"]),
            metadata=loads(row["metadata_json"]) or {},
        )
        return plan

    def list_plans(self, run_id: Optional[str] = None) -> List[ExecutionPlan]:
        sql = f"SELECT id FROM {schema.PLANS}"
        args: tuple = ()
        if run_id is not None:
            sql += " WHERE run_id=?"
            args = (run_id,)
        with self._lock:
            rows = self._acquire().execute(sql, args).fetchall()
        return [self.get_plan(r["id"]) for r in rows]

    # ── steps ────────────────────────────────────────────────────────

    def save_step(self, plan_id: str, step: ExecutionStep) -> None:
        """Idempotent upsert (retry-safe). Arguments are scrubbed on write."""
        with self._lock:
            conn = self._acquire()
            conn.execute(
                f"""
                INSERT INTO {schema.STEPS} (
                    id, plan_id, run_id, sequence, name, description, tool,
                    arguments_json, requires_approval, status, result_json, error,
                    created_at, started_at, completed_at, updated_at, version
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(plan_id, id) DO UPDATE SET
                    status=excluded.status, result_json=excluded.result_json,
                    error=excluded.error, updated_at=excluded.updated_at
                """,
                self._step_row(conn, plan_id, step),
            )

    def update_step(self, plan_id: str, step: ExecutionStep, expected_version: Optional[int] = None) -> None:
        """Version-guarded update — raises ConcurrentUpdateError on conflict."""
        with self._lock:
            conn = self._acquire()
            existing = conn.execute(
                f"SELECT version FROM {schema.STEPS} WHERE id=?", (step.id,)
            ).fetchone()
            if existing is None:
                raise ExecutionErrorBase(f"step not found: {step.id}")
            base = existing["version"] if expected_version is None else expected_version
            row = self._step_row(conn, plan_id, step)
            cur = conn.execute(
                f"""
                UPDATE {schema.STEPS} SET
                    status=?, result_json=?, error=?, updated_at=?, version=?
                WHERE id=? AND version=?
                """,
                (
                    row[9], row[10], row[11], row[15],
                    base + 1, step.id, base,
                ),
            )
            if cur.rowcount == 0:
                raise ConcurrentUpdateError(schema.STEPS, step.id)

    def get_step(self, plan_id: str, step_id: str) -> ExecutionStep:
        with self._lock:
            row = self._acquire().execute(
                f"SELECT * FROM {schema.STEPS} WHERE id=? AND plan_id=?",
                (step_id, plan_id),
            ).fetchone()
        if row is None:
            raise ExecutionErrorBase(f"step not found: {plan_id}/{step_id}")
        return self._step_from_row(row)

    def list_steps(self, plan_id: str) -> List[ExecutionStep]:
        with self._lock:
            rows = self._acquire().execute(
                f"SELECT * FROM {schema.STEPS} WHERE plan_id=? ORDER BY sequence",
                (plan_id,),
            ).fetchall()
        return [self._step_from_row(r) for r in rows]

    def _step_row(self, conn: sqlite3.Connection, plan_id: str, step: ExecutionStep) -> tuple:
        data = step.to_dict()
        row = conn.execute(
            f"SELECT run_id FROM {schema.PLANS} WHERE id=?", (plan_id,)
        ).fetchone()
        run_id = row["run_id"] if row is not None else plan_id
        return (
            data["id"], plan_id, run_id,
            int(data.get("sequence", 0)),
            data["name"], data["description"], data["tool"],
            dumps(redaction.scrub(data.get("arguments"))),
            1 if data.get("requires_approval") else 0,
            data["status"], dumps(redaction.scrub(data.get("result"))), data["error"],
            None, None, None, _now(), 1,
        )

    def _step_from_row(self, row: sqlite3.Row) -> ExecutionStep:
        return ExecutionStep(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            tool=row["tool"],
            arguments=loads(row["arguments_json"]) or {},
            requires_approval=bool(row["requires_approval"]),
            status=StepStatus(row["status"]),
            result=loads(row["result_json"]),
            error=row["error"],
        )

    # ── approvals ────────────────────────────────────────────────────

    _NEW_APPROVAL_COLUMNS = ("decided_by", "decision_source", "decision_reason_code")

    def _approval_new_columns(self, conn) -> tuple:
        """Columns present in the approvals table (old vs migrated schema)."""
        try:
            cols = {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({schema.APPROVALS})")
            }
            return tuple(c for c in self._NEW_APPROVAL_COLUMNS if c in cols)
        except Exception:
            return ()

    def save_approval(self, request: ApprovalRequest) -> None:
        data = request.to_dict()
        with self._lock:
            conn = self._acquire()
            new_cols = self._approval_new_columns(conn)
            cols = ["id", "run_id", "step_id", "reason", "status", "created_at",
                    "expires_at", "decided_at", "decision_reason"] + list(new_cols)
            cols += ["version", "updated_at"]
            placeholders = ",".join("?" for _ in cols)
            values = [
                data["id"], data["run_id"], data["step_id"], data["reason"],
                data["status"], data["created_at"], data["expires_at"],
                None, None,
            ] + [data.get(c) for c in new_cols]
            values += [1, _now()]
            conn.execute(
                f"""
                INSERT INTO {schema.APPROVALS} ({",".join(cols)})
                VALUES ({placeholders})
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status, decided_at=excluded.decided_at,
                    decision_reason=excluded.decision_reason,
                    decided_by=excluded.decided_by,
                    decision_source=excluded.decision_source,
                    decision_reason_code=excluded.decision_reason_code,
                    updated_at=excluded.updated_at
                """,
                tuple(values),
            )

    def get_approval(self, approval_id: str) -> ApprovalRequest:
        with self._lock:
            row = self._acquire().execute(
                f"SELECT * FROM {schema.APPROVALS} WHERE id=?", (approval_id,)
            ).fetchone()
        if row is None:
            raise ExecutionErrorBase(f"approval not found: {approval_id}")
        return self._approval_from_row(row)

    def update_approval(self, request: ApprovalRequest, expected_version: Optional[int] = None) -> None:
        """Version-guarded decision write — atomic double-decision guard."""
        data = request.to_dict()
        with self._lock:
            conn = self._acquire()
            existing = conn.execute(
                f"SELECT version FROM {schema.APPROVALS} WHERE id=?", (request.id,)
            ).fetchone()
            if existing is None:
                raise ExecutionErrorBase(f"approval not found: {request.id}")
            base = existing["version"] if expected_version is None else expected_version
            new_cols = self._approval_new_columns(conn)
            set_clause = "status=?, decided_at=?, decision_reason=?"
            values: list = [data["status"], _now(), data.get("decision_reason")]
            for col in new_cols:
                set_clause += f", {col}=?"
                values.append(data.get(col))
            set_clause += ", version=?, updated_at=?"
            values += [base + 1, _now(), request.id, base]
            cur = conn.execute(
                f"""
                UPDATE {schema.APPROVALS} SET {set_clause}
                WHERE id=? AND version=?
                """,
                tuple(values),
            )
            if cur.rowcount == 0:
                raise ConcurrentUpdateError(schema.APPROVALS, request.id)

    def list_approvals(self, run_id: Optional[str] = None) -> List[ApprovalRequest]:
        sql = f"SELECT * FROM {schema.APPROVALS}"
        args: tuple = ()
        if run_id is not None:
            sql += " WHERE run_id=?"
            args = (run_id,)
        with self._lock:
            rows = self._acquire().execute(sql, args).fetchall()
        return [self._approval_from_row(r) for r in rows]

    def _approval_from_row(self, row: sqlite3.Row) -> ApprovalRequest:
        def _get(name: str, default=None):
            try:
                return row[name]
            except (IndexError, KeyError):
                return default

        return ApprovalRequest(
            id=row["id"],
            run_id=row["run_id"],
            step_id=row["step_id"],
            reason=row["reason"],
            status=ApprovalStatus(row["status"]),
            created_at=parse_timestamp(row["created_at"]),
            expires_at=parse_timestamp(row["expires_at"]),
            decided_by=_get("decided_by"),
            decision_source=_get("decision_source"),
            decision_reason_code=_get("decision_reason_code"),
        )

    # ── event journal (append-only) ─────────────────────────────────

    def append_event(
        self,
        event: RuntimeEvent,
        step_id: Optional[str] = None,
        input_hash: Optional[str] = None,
        output_hash: Optional[str] = None,
    ) -> int:
        """Append one event row. NEVER updates existing rows (append-only)."""
        with self._lock:
            conn = self._acquire()
            cur = conn.execute(
                f"""
                INSERT INTO {schema.EVENTS} (
                    run_id, step_id, event_type, timestamp, payload_json,
                    input_hash, output_hash
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    event.run_id,
                    step_id or event.payload.get("step"),
                    event.event_type,
                    event.timestamp.isoformat() if event.timestamp else _now(),
                    dumps(redaction.scrub(event.payload)),
                    input_hash, output_hash,
                ),
            )
            return int(cur.lastrowid or 0)

    def list_events(
        self,
        run_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[RuntimeEvent]:
        """Events in journal order (rowid = unambiguous ordering)."""
        sql = f"SELECT * FROM {schema.EVENTS}"
        clauses: List[str] = []
        args: List[Any] = []
        if run_id is not None:
            clauses.append("run_id=?")
            args.append(run_id)
        if event_type is not None:
            clauses.append("event_type=?")
            args.append(event_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        with self._lock:
            rows = self._acquire().execute(sql, tuple(args)).fetchall()
        return [
            RuntimeEvent(
                event_type=r["event_type"],
                run_id=r["run_id"],
                timestamp=parse_timestamp(r["timestamp"]) or datetime.now(timezone.utc),
                payload=loads(r["payload_json"]) or {},
            )
            for r in rows
        ]
