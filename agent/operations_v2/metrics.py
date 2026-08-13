"""Canary metrics (Sprint 1.0.6.3 §11-14) — read-only aggregations.

Computed from the durable agent_v2_* tables (runs/steps/approvals/
events) — NO separate telemetry DB, no duplicated data. All queries are
read-only; latency percentiles are honest (sample counts reported,
never fabricated precision on tiny samples).

Windows: ``1h`` / ``24h`` / ``all`` (created_at / timestamp bounds).
"""

import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from agent.persistence.schema import APPROVALS, EVENTS, RUNS

from .models import ErrorCode

WINDOWS = {"1h": 60, "24h": 1440, "all": None}
_TOOL_EVENT_TYPES = ("TOOL_STARTED", "TOOL_COMPLETED", "TOOL_FAILED")
_STOP_TO_TAXONOMY = {
    "invalid_plan": ErrorCode.INVALID_PLAN,
    "no_plan": ErrorCode.INVALID_PLAN,
    "approval_required": ErrorCode.APPROVAL_REQUIRED,
    "manual_review_required": ErrorCode.MANUAL_REVIEW,
    "max_steps": ErrorCode.BUDGET_EXCEEDED,
    "max_tool_calls": ErrorCode.BUDGET_EXCEEDED,
    "max_replans": ErrorCode.BUDGET_EXCEEDED,
    "max_failures": ErrorCode.BUDGET_EXCEEDED,
    "runtime_timeout": ErrorCode.BUDGET_EXCEEDED,
}


def _connect_ro(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _cutoff(window: str) -> Optional[str]:
    minutes = WINDOWS.get(window)
    if minutes is None:
        return None
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _pct(sorted_values: List[float], pct: float) -> Optional[float]:
    if not sorted_values:
        return None
    idx = max(0, min(len(sorted_values) - 1,
                     int(math.ceil(len(sorted_values) * pct)) - 1))
    return round(sorted_values[idx], 1)


class CanaryMetrics:
    """Aggregate counters / success rate / latency / error taxonomy."""

    def __init__(self, db_path: str) -> None:
        if not os.path.exists(db_path):
            raise FileNotFoundError(db_path)
        self._db = db_path

    def compute(self, window: str = "24h") -> Dict[str, Any]:
        if window not in WINDOWS:
            raise ValueError(f"window must be one of {sorted(WINDOWS)}")
        cutoff = _cutoff(window)
        conn = _connect_ro(self._db)
        try:
            runs = self._run_counts(conn, cutoff)
            approvals = self._approval_counts(conn, cutoff)
            events = self._event_counts(conn, cutoff)
            taxonomy = self._taxonomy(conn, cutoff, runs, events)
            duplicates = self._duplicate_open_actions(conn, cutoff)
            run_durations = self._run_durations(conn, cutoff)
            tool_durations = self._tool_durations(conn, cutoff)
        finally:
            conn.close()

        terminal = runs["completed"] + runs["failed"] + runs["cancelled"]
        success_rate = (
            round(runs["completed"] / terminal * 100.0, 1) if terminal else None
        )
        return {
            "window": window,
            "runs_total": runs["total"],
            "runs_completed": runs["completed"],
            "runs_failed": runs["failed"],
            "runs_waiting_approval": runs["waiting_approval"],
            "runs_manual_review": runs["manual_review"],
            "runs_cancelled": runs["cancelled"],
            "runs_incomplete": runs["incomplete"],
            "canary_success_rate": success_rate,
            "canary_success_denominator": terminal,
            "tool_calls_total": events["tool_started"],
            "tool_failures": max(0, events["tool_failed"] - events["tool_timeouts"]),
            "tool_timeouts": events["tool_timeouts"],
            "approval_pending": approvals.get("pending", 0),
            "approval_approved": approvals.get("approved", 0),
            "approval_rejected": approvals.get("rejected", 0),
            "approval_expired": approvals.get("expired", 0),
            "recovery_incomplete": runs["incomplete"],
            "recovery_manual_review": events["recovery_manual_review"],
            "duplicate_action_detected": duplicates,
            "runtime_budget_exceeded": events["budget_exceeded"],
            "error_taxonomy": {k.value: v for k, v in taxonomy.items() if v},
            "latency_ms": {
                "p50_run_duration": _pct(run_durations, 0.5),
                "p95_run_duration": _pct(run_durations, 0.95),
                "run_duration_samples": len(run_durations),
                "p50_tool_duration": _pct(tool_durations, 0.5),
                "p95_tool_duration": _pct(tool_durations, 0.95),
                "tool_duration_samples": len(tool_durations),
            },
        }

    # ── internals ────────────────────────────────────────────────────

    def _run_counts(self, conn, cutoff: Optional[str]) -> Dict[str, int]:
        where, args = self._where("created_at", cutoff)
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS n FROM {RUNS}{where} GROUP BY status",
            args,
        ).fetchall()
        counts = {r["status"]: r["n"] for r in rows}
        pending_approval = conn.execute(
            f"SELECT COUNT(DISTINCT a.run_id) AS n FROM {APPROVALS} a "
            f"JOIN {RUNS} r ON r.id=a.run_id "
            f"WHERE a.status='pending'{self._and_ts('r.created_at', cutoff)}",
            (*self._args(cutoff),),
        ).fetchone()["n"]
        manual_review_runs = conn.execute(
            f"SELECT COUNT(DISTINCT e.run_id) AS n FROM {EVENTS} e "
            f"WHERE e.event_type='RECOVERY_MANUAL_REVIEW'{self._and_ts('e.timestamp', cutoff)}",
            (*self._args(cutoff),),
        ).fetchone()["n"]
        return {
            "total": counts.get("completed", 0) + counts.get("failed", 0)
                     + counts.get("cancelled", 0)
                     + sum(v for k, v in counts.items()
                           if k not in ("completed", "failed", "cancelled")),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
            "waiting_approval": pending_approval,
            "manual_review": manual_review_runs,
            "incomplete": conn.execute(
                f"SELECT COUNT(*) AS n FROM {RUNS} "
                f"WHERE status NOT IN ('completed','failed','cancelled')"
                f"{self._and_ts('created_at', cutoff)}",
                (*self._args(cutoff),),
            ).fetchone()["n"],
        }

    def _approval_counts(self, conn, cutoff: Optional[str]) -> Dict[str, int]:
        rows = conn.execute(
            f"SELECT a.status, COUNT(*) AS n FROM {APPROVALS} a "
            f"JOIN {RUNS} r ON r.id=a.run_id "
            f"WHERE 1=1{self._and_ts('r.created_at', cutoff)} GROUP BY a.status",
            (*self._args(cutoff),),
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def _event_counts(self, conn, cutoff: Optional[str]) -> Dict[str, int]:
        where, args = self._where("timestamp", cutoff)
        rows = conn.execute(
            f"SELECT event_type, COUNT(*) AS n FROM {EVENTS}{where} "
            f"GROUP BY event_type",
            args,
        ).fetchall()
        counts = {r["event_type"]: r["n"] for r in rows}
        timeout_rows = conn.execute(
            f"SELECT COUNT(*) AS n FROM {EVENTS} "
            f"WHERE event_type='TOOL_FAILED' AND payload_json LIKE '%timeout%'"
            f"{self._and_ts('timestamp', cutoff)}",
            (*self._args(cutoff),),
        ).fetchone()
        return {
            "tool_started": counts.get("TOOL_STARTED", 0),
            "tool_failed": counts.get("TOOL_FAILED", 0),
            "tool_timeouts": timeout_rows["n"],
            "recovery_manual_review": counts.get("RECOVERY_MANUAL_REVIEW", 0),
            "budget_exceeded": counts.get("BUDGET_EXCEEDED", 0),
        }

    def _taxonomy(self, conn, cutoff, runs, events) -> Dict[ErrorCode, int]:
        taxonomy: Dict[ErrorCode, int] = {
            ErrorCode.INVALID_PLAN: 0,
            ErrorCode.TOOL_TIMEOUT: 0,
            ErrorCode.TOOL_FAILED: 0,
            ErrorCode.APPROVAL_REQUIRED: 0,
            ErrorCode.MANUAL_REVIEW: 0,
            ErrorCode.BUDGET_EXCEEDED: 0,
            ErrorCode.INTERNAL_ERROR: 0,
        }
        taxonomy[ErrorCode.TOOL_TIMEOUT] = events["tool_timeouts"]
        taxonomy[ErrorCode.TOOL_FAILED] = max(
            0, events["tool_failed"] - events["tool_timeouts"]
        )
        where, args = self._where("timestamp", cutoff)
        rows = conn.execute(
            f"SELECT run_id, event_type, payload_json FROM {EVENTS}{where}"
            f"{' AND' if where else ' WHERE'} event_type IN "
            f"('ORCHESTRATION_STOPPED','RECOVERY_MANUAL_REVIEW','BUDGET_EXCEEDED')",
            args,
        ).fetchall()
        import json

        stopped_runs: Dict[str, str] = {}
        for row in rows:
            if row["event_type"] == "ORCHESTRATION_STOPPED":
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except ValueError:
                    payload = {}
                if payload.get("stop_reason"):
                    stopped_runs.setdefault(row["run_id"], payload["stop_reason"])
            elif row["event_type"] == "RECOVERY_MANUAL_REVIEW":
                taxonomy[ErrorCode.MANUAL_REVIEW] += 1
            elif row["event_type"] == "BUDGET_EXCEEDED":
                taxonomy[ErrorCode.BUDGET_EXCEEDED] += 1
        for stop_reason in stopped_runs.values():
            code = _STOP_TO_TAXONOMY.get(stop_reason)
            if code is not None:
                taxonomy[code] += 1
        # INTERNAL_ERROR: failed runs not explained by any structured cause.
        explained = runs["failed"]
        explained -= sum(
            taxonomy[c] for c in (ErrorCode.INVALID_PLAN, ErrorCode.TOOL_FAILED,
                                  ErrorCode.TOOL_TIMEOUT, ErrorCode.MANUAL_REVIEW,
                                  ErrorCode.BUDGET_EXCEEDED)
        )
        taxonomy[ErrorCode.INTERNAL_ERROR] = max(0, explained)
        return taxonomy

    def _duplicate_open_actions(self, conn, cutoff: Optional[str]) -> int:
        """(run, step) pairs with TOOL_STARTED but no TOOL_COMPLETED/FAILED."""
        where, args = self._where("timestamp", cutoff)
        rows = conn.execute(
            f"SELECT run_id, step_id, event_type FROM {EVENTS}{where}"
            f"{' AND' if where else ' WHERE'} event_type IN {_TOOL_EVENT_TYPES} "
            f"ORDER BY id",
            args,
        ).fetchall()
        open_steps: Dict[tuple, bool] = {}
        for row in rows:
            key = (row["run_id"], row["step_id"])
            if row["event_type"] == "TOOL_STARTED":
                open_steps[key] = True
            else:  # TOOL_COMPLETED / TOOL_FAILED closes the attempt
                open_steps[key] = False
        return sum(1 for v in open_steps.values() if v)

    def _run_durations(self, conn, cutoff: Optional[str]) -> List[float]:
        where, args = self._where("created_at", cutoff)
        rows = conn.execute(
            f"SELECT started_at, completed_at FROM {RUNS}{where}"
            f"{' AND' if where else ' WHERE'} status='completed' "
            f"AND started_at IS NOT NULL AND completed_at IS NOT NULL",
            args,
        ).fetchall()
        durations: List[float] = []
        for row in rows:
            try:
                start = datetime.fromisoformat(row["started_at"])
                end = datetime.fromisoformat(row["completed_at"])
            except ValueError:
                continue
            durations.append((end - start).total_seconds() * 1000.0)
        return sorted(durations)

    def _tool_durations(self, conn, cutoff: Optional[str]) -> List[float]:
        where, args = self._where("timestamp", cutoff)
        rows = conn.execute(
            f"SELECT run_id, step_id, event_type, timestamp FROM {EVENTS}{where}"
            f"{' AND' if where else ' WHERE'} event_type IN {_TOOL_EVENT_TYPES} "
            f"ORDER BY id",
            args,
        ).fetchall()
        starts: Dict[tuple, datetime] = {}
        durations: List[float] = []
        for row in rows:
            try:
                ts = datetime.fromisoformat(row["timestamp"])
            except (ValueError, TypeError):
                continue
            key = (row["run_id"], row["step_id"])
            if row["event_type"] == "TOOL_STARTED":
                starts[key] = ts
            elif row["event_type"] == "TOOL_COMPLETED" and key in starts:
                durations.append((ts - starts.pop(key)).total_seconds() * 1000.0)
            elif row["event_type"] == "TOOL_FAILED" and key in starts:
                starts.pop(key)  # failed attempts carry no completion
        return sorted(durations)

    @staticmethod
    def _where(column: str, cutoff: Optional[str]) -> tuple:
        if cutoff is None:
            return "", ()
        return f" WHERE {column}>=?", (cutoff,)

    @staticmethod
    def _and_ts(column: str, cutoff: Optional[str]) -> str:
        return f" AND {column}>=?" if cutoff else ""

    @staticmethod
    def _args(cutoff: Optional[str]) -> tuple:
        return (cutoff,) if cutoff else ()
