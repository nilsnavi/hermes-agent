"""Run inspector (Sprint 1.0.6.3 §7-9) — READ-ONLY run/step/event views.

Every method opens the store database with ``mode=ro`` (zero writes by
construction) and returns safe DTOs (RunSummary / RunTimelineItem /
ApprovalView / ManualReviewItemDTO / StaleRun). No prompts, no raw
arguments, no raw outputs ever leave this layer.

Aggregate reads use single SQL passes with correlated subqueries over
the run_id indexes — no N+1 loops over hundreds of runs.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent.persistence.schema import APPROVALS, EVENTS, PLANS, RUNS, STEPS

from .exceptions import ApprovalNotFound, RunNotFound
from .models import ApprovalView, RunSummary, RunTimelineItem, StaleRun
from .serializers import summarize_event_payload

TERMINAL_STATUSES = ("completed", "failed", "cancelled")

_MAX_LIST_LIMIT = 500
_DEFAULT_LIST_LIMIT = 50


def _connect_ro(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _iso(ts: Any) -> Optional[str]:
    return ts if ts else None


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _duration_ms(started: Optional[str], completed: Optional[str],
                 created: Optional[str]) -> Optional[int]:
    start = _parse_dt(started) or _parse_dt(created)
    end = _parse_dt(completed)
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


class RunInspector:
    """Safe read-only views over the durable V2 state."""

    def __init__(self, db_path: str) -> None:
        if not os.path.exists(db_path):
            raise FileNotFoundError(db_path)
        self._db = db_path

    # ── runs ─────────────────────────────────────────────────────────

    def get_run(self, run_id: str) -> RunSummary:
        conn = _connect_ro(self._db)
        try:
            row = conn.execute(f"SELECT * FROM {RUNS} WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise RunNotFound(run_id)
            return self._summary_from_row(conn, row)
        finally:
            conn.close()

    def list_runs(
        self,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        limit: int = _DEFAULT_LIST_LIMIT,
    ) -> List[RunSummary]:
        """Bounded run listing (default 50, hard max 500) — newest first."""
        limit = max(1, min(int(limit), _MAX_LIST_LIMIT))
        clauses: List[str] = []
        args: List[Any] = []
        if status:
            clauses.append("r.status=?")
            args.append(status)
        if task_type:
            clauses.append("r.task_type=?")
            args.append(task_type)
        if from_ts:
            clauses.append("r.created_at>=?")
            args.append(from_ts)
        if to_ts:
            clauses.append("r.created_at<=?")
            args.append(to_ts)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = _connect_ro(self._db)
        try:
            rows = conn.execute(
                f"SELECT * FROM {RUNS} r{where} ORDER BY r.created_at DESC LIMIT ?",
                (*args, limit),
            ).fetchall()
            return [self._summary_from_row(conn, r) for r in rows]
        finally:
            conn.close()

    def get_incomplete_runs(self) -> List[RunSummary]:
        """Every non-terminal run (recovery candidates)."""
        conn = _connect_ro(self._db)
        try:
            rows = conn.execute(
                f"SELECT * FROM {RUNS} WHERE status NOT IN (?,?,?) "
                f"ORDER BY created_at",
                TERMINAL_STATUSES,
            ).fetchall()
            return [self._summary_from_row(conn, r) for r in rows]
        finally:
            conn.close()

    # ── timeline (§9 / §56) ──────────────────────────────────────────

    def get_run_timeline(
        self,
        run_id: str,
        limit: int = 200,
        before: Optional[int] = None,
        after: Optional[int] = None,
    ) -> List[RunTimelineItem]:
        """Journal items in event-id ascending order (cursor pagination)."""
        self.get_run(run_id)  # 404 guard
        limit = max(1, min(int(limit), 1000))
        clauses = "run_id=?"
        args: List[Any] = [run_id]
        if before is not None:
            clauses += " AND id<?"
            args.append(int(before))
        if after is not None:
            clauses += " AND id>?"
            args.append(int(after))
        conn = _connect_ro(self._db)
        try:
            rows = conn.execute(
                f"SELECT * FROM {EVENTS} WHERE {clauses} ORDER BY id LIMIT ?",
                (*args, limit),
            ).fetchall()
            return [self._timeline_from_row(r) for r in rows]
        finally:
            conn.close()

    # ── approvals ────────────────────────────────────────────────────

    def list_approvals(
        self,
        run_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[ApprovalView]:
        limit = max(1, min(int(limit), 500))
        clauses: List[str] = []
        args: List[Any] = []
        if run_id:
            clauses.append("a.run_id=?")
            args.append(run_id)
        if status:
            clauses.append("a.status=?")
            args.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = _connect_ro(self._db)
        try:
            rows = conn.execute(
                f"SELECT a.*, s.tool AS tool, r.task_type AS task_type "
                f"FROM {APPROVALS} a "
                f"LEFT JOIN {STEPS} s ON s.run_id=a.run_id AND s.id=a.step_id "
                f"LEFT JOIN {RUNS} r ON r.id=a.run_id "
                f"{where} ORDER BY a.created_at DESC LIMIT ?",
                (*args, limit),
            ).fetchall()
            return [self._approval_from_row(r) for r in rows]
        finally:
            conn.close()

    def get_approval(self, approval_id: str) -> ApprovalView:
        conn = _connect_ro(self._db)
        try:
            row = conn.execute(
                f"SELECT a.*, s.tool AS tool, r.task_type AS task_type "
                f"FROM {APPROVALS} a "
                f"LEFT JOIN {STEPS} s ON s.run_id=a.run_id AND s.id=a.step_id "
                f"LEFT JOIN {RUNS} r ON r.id=a.run_id "
                f"WHERE a.id=?",
                (approval_id,),
            ).fetchone()
            if row is None:
                raise ApprovalNotFound(approval_id)
            return self._approval_from_row(row)
        finally:
            conn.close()

    def get_waiting_approvals(self) -> List[ApprovalView]:
        return self.list_approvals(status="pending")

    # ── stale runs (§44) ─────────────────────────────────────────────

    def get_stale_runs(self, threshold_minutes: int = 60) -> List[StaleRun]:
        """Incomplete runs with no journal activity past the threshold.

        Detection only — NEVER auto-fixes. Classification:
        - WAIT_FOR_APPROVAL past expiry / older than threshold →
          STALE_APPROVAL;
        - RUNNING / VERIFYING / other active states with no event past
          the threshold → STALE_RUN.
        """
        cutoff = _now_utc() - timedelta(minutes=max(1, threshold_minutes))
        stale: List[StaleRun] = []
        for summary in self.get_incomplete_runs():
            last_at = _parse_dt(summary.last_event_at)
            if last_at is None or last_at >= cutoff:
                continue
            waiting_since = summary.last_event_at
            if summary.recovery_disposition == "wait_for_approval":
                reason = "STALE_APPROVAL"
            elif summary.status in ("running", "tool_execution", "verifying"):
                reason = "STALE_RUN"
            else:
                reason = "STALE_RUN"
            stale.append(StaleRun(
                run_id=summary.run_id,
                status=summary.status,
                disposition=summary.recovery_disposition or "",
                waiting_since=waiting_since,
                stale_reason=reason,
            ))
        return stale

    # ── internals ────────────────────────────────────────────────────

    def _summary_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> RunSummary:
        run_id = row["id"]
        counts = conn.execute(
            f"""
            SELECT
              (SELECT COUNT(*) FROM {STEPS} s WHERE s.run_id=?) AS step_count,
              (SELECT COUNT(*) FROM {STEPS} s WHERE s.run_id=? AND s.status='completed') AS completed_steps,
              (SELECT COUNT(*) FROM {STEPS} s WHERE s.run_id=? AND s.status='failed') AS failed_steps,
              (SELECT COUNT(*) FROM {EVENTS} e WHERE e.run_id=? AND e.event_type='TOOL_STARTED') AS tool_calls,
              (SELECT COUNT(*) FROM {APPROVALS} a WHERE a.run_id=?) AS approval_count
            """,
            (run_id, run_id, run_id, run_id, run_id),
        ).fetchone()
        plan = conn.execute(
            f"SELECT status FROM {PLANS} WHERE run_id=? ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        last_event = conn.execute(
            f"SELECT event_type, timestamp FROM {EVENTS} WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return RunSummary(
            run_id=run_id,
            status=row["status"],
            task_type=row["task_type"],
            created_at=_iso(row["created_at"]),
            started_at=_iso(row["started_at"]),
            completed_at=_iso(row["completed_at"]),
            duration_ms=_duration_ms(row["started_at"], row["completed_at"],
                                     row["created_at"]),
            plan_status=plan["status"] if plan else None,
            step_count=counts["step_count"] or 0,
            completed_steps=counts["completed_steps"] or 0,
            failed_steps=counts["failed_steps"] or 0,
            tool_calls=counts["tool_calls"] or 0,
            approval_count=counts["approval_count"] or 0,
            stop_reason=None,  # populated by the service (event-derived)
            recovery_disposition=None,  # populated by the service
            last_event_type=last_event["event_type"] if last_event else None,
            last_event_at=_iso(last_event["timestamp"]) if last_event else None,
        )

    def _timeline_from_row(self, row: sqlite3.Row) -> RunTimelineItem:
        payload = _safe_loads(row["payload_json"])
        summary = summarize_event_payload(row["event_type"], payload)
        step_id = row["step_id"] or summary.get("step_id")
        tool_name = summary.get("tool_name")
        status = summary.get("status")
        reason_code = summary.get("error_class") or summary.get("stop_reason")
        input_hash = row["input_hash"] or summary.get("input_hash")
        output_hash = row["output_hash"] or summary.get("output_hash")
        return RunTimelineItem(
            event_id=row["id"],
            timestamp=_iso(row["timestamp"]),
            event_type=row["event_type"],
            step_id=step_id,
            tool_name=tool_name,
            status=status,
            reason_code=reason_code,
            input_hash=input_hash,
            output_hash=output_hash,
        )

    @staticmethod
    def _approval_from_row(row: sqlite3.Row) -> ApprovalView:
        def _get(name: str, default=None):
            try:
                return row[name]
            except (IndexError, KeyError):
                return default

        return ApprovalView(
            approval_id=row["id"],
            run_id=row["run_id"],
            step_id=row["step_id"],
            tool=row["tool"],
            task_type=row["task_type"],
            reason=row["reason"] or "",
            status=row["status"],
            risk=None,
            side_effect=None,
            created_at=_iso(row["created_at"]),
            expires_at=_iso(row["expires_at"]),
            decided_at=_iso(row["decided_at"]),
            decided_by=_get("decided_by"),
            decision_source=_get("decision_source"),
            decision_reason_code=_get("decision_reason_code"),
            version=row["version"] or 1,
        )


def _safe_loads(raw: Optional[str]) -> Dict[str, Any]:
    import json

    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}
