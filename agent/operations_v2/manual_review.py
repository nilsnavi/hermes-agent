"""Manual review reconstruction (Sprint 1.0.6.3 §41-43).

The queue itself is in-memory per recovery process (existing
ManualReviewQueue), but the OPERATIONS layer reconstructs the pending
manual-review set from DURABLE state + the audit journal, so the list
never disappears after a restart:

1. every run carrying a ``RECOVERY_MANUAL_REVIEW`` journal event;
2. every non-terminal run whose journal has an OPEN tool attempt
   (TOOL_STARTED without TOOL_COMPLETED/TOOL_FAILED) — the ambiguous
   outcome class.

Inspect only — no mark-completed / retry actions (operator resolution
is a later sprint).
"""

from typing import Any, Dict, List, Optional

from .models import ManualReviewItemDTO
from .run_inspector import RunInspector

_OPEN_TOOL_EVENTS = ("TOOL_STARTED", "TOOL_COMPLETED", "TOOL_FAILED")


class ManualReviewOps:
    """Durable manual-review visibility for operators."""

    def __init__(self, db_path: str) -> None:
        self._inspector = RunInspector(db_path)
        self._db = db_path

    def list_pending(self) -> List[ManualReviewItemDTO]:
        """Reconstructed pending manual-review items (restart-proof)."""
        items: Dict[str, Dict[str, Any]] = {}

        # 1) runs explicitly flagged by the recovery layer.
        for event in self._manual_review_events():
            run_id = event["run_id"]
            item = items.setdefault(run_id, {
                "run_id": run_id, "reason": event["reason"],
                "created_at": event["timestamp"],
            })
            if item.get("reason") is None:
                item["reason"] = event["reason"]
            if item.get("created_at") is None:
                item["created_at"] = event["timestamp"]

        # 2) open tool attempts (ambiguous outcome) on non-terminal runs.
        for run in self._inspector.get_incomplete_runs():
            open_step = self._open_tool_attempt(run.run_id)
            if open_step is None:
                continue
            item = items.setdefault(run.run_id, {
                "run_id": run.run_id, "reason": None, "created_at": None,
            })
            if item.get("reason") is None:
                item["reason"] = (
                    f"ambiguous tool outcome: {open_step['tool']} "
                    f"started without completion"
                )
            if item.get("created_at") is None:
                item["created_at"] = run.created_at

        # 3) classify + enrich from the inspector.
        out: List[ManualReviewItemDTO] = []
        for run_id, meta in sorted(items.items()):
            summary = self._inspector.get_run(run_id)
            open_step = self._open_tool_attempt(run_id)
            out.append(ManualReviewItemDTO(
                run_id=run_id,
                step_id=(open_step or {}).get("step_id"),
                tool=(open_step or {}).get("tool"),
                reason=meta.get("reason") or "manual review required",
                last_event_type=summary.last_event_type,
                last_event_at=summary.last_event_at,
                recovery_disposition="manual_review",
                created_at=meta.get("created_at") or summary.created_at,
                recommended_actions=self._recommended_actions(summary.status),
            ))
        return out

    # ── internals ────────────────────────────────────────────────────

    def _manual_review_events(self) -> List[Dict[str, Any]]:
        import sqlite3

        conn = sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT run_id, timestamp, payload_json FROM agent_v2_events "
                "WHERE event_type='RECOVERY_MANUAL_REVIEW' ORDER BY id"
            ).fetchall()
            out = []
            for row in rows:
                payload = _loads(row["payload_json"])
                out.append({
                    "run_id": row["run_id"],
                    "timestamp": row["timestamp"],
                    "reason": payload.get("reason") or "manual review required",
                })
            return out
        finally:
            conn.close()

    def _open_tool_attempt(self, run_id: str) -> Optional[Dict[str, Any]]:
        timeline = self._inspector.get_run_timeline(run_id, limit=1000)
        open_steps: Dict[str, Dict[str, Any]] = {}
        for item in timeline:
            if item.event_type not in _OPEN_TOOL_EVENTS:
                continue
            if item.step_id is None:
                continue
            key = item.step_id
            if item.event_type == "TOOL_STARTED":
                open_steps[key] = {
                    "step_id": item.step_id, "tool": item.tool_name,
                }
            else:  # TOOL_COMPLETED / TOOL_FAILED closes the attempt
                open_steps.pop(key, None)
        return next(iter(open_steps.values()), None)

    @staticmethod
    def _recommended_actions(run_status: str) -> List[str]:
        if run_status in ("completed", "failed", "cancelled"):
            return ["review run outcome; no action required"]
        return [
            "inspect run timeline: python -m agent.operations_v2.cli "
            "timeline <run-id>",
            "decide manually; do NOT auto-resume an ambiguous tool",
        ]


def _loads(raw: Optional[str]) -> Dict[str, Any]:
    import json

    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}
