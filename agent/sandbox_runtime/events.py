"""Sandbox audit events (Sprint 1.3.5 §29) — append-only, RuntimeEvent-compatible."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

#: Full event vocabulary — order of emission is the audit order.
SANDBOX_EVENTS = (
    "SANDBOX_MUTATION_REQUESTED",
    "SANDBOX_PLAN_CREATED",
    "SANDBOX_PREFLIGHT_STARTED",
    "SANDBOX_PREFLIGHT_PASSED",
    "SANDBOX_PREFLIGHT_FAILED",
    "SANDBOX_APPROVAL_VALIDATED",
    "SANDBOX_SNAPSHOT_CREATED",
    "SANDBOX_LOCK_ACQUIRED",
    "SANDBOX_EXECUTION_STARTED",
    "SANDBOX_EXECUTION_COMPLETED",
    "SANDBOX_EXECUTION_FAILED",
    "SANDBOX_VERIFY_STARTED",
    "SANDBOX_VERIFY_PASSED",
    "SANDBOX_VERIFY_FAILED",
    "SANDBOX_HEALTH_PASSED",
    "SANDBOX_HEALTH_FAILED",
    "SANDBOX_COMMITTED",
    "SANDBOX_ROLLBACK_STARTED",
    "SANDBOX_ROLLED_BACK",
    "SANDBOX_ROLLBACK_FAILED",
    "SANDBOX_UNKNOWN_OUTCOME",
    "SANDBOX_MANUAL_REVIEW_REQUIRED",
    "SANDBOX_RECOVERY_SCAN_STARTED",
    "SANDBOX_RECOVERY_SCAN_COMPLETED",
    "SANDBOX_RECONCILIATION_COMPLETED",
    "SANDBOX_SNAPSHOT_CORRUPT",
    "SANDBOX_LOCK_STATE_AMBIGUOUS",
    "SANDBOX_CHAOS_INJECTED",
    # Sprint 1.3.6 canonical recovery journal vocabulary.
    "SANDBOX_PROCESS_CRASH_DETECTED",
    "SANDBOX_RECOVERY_CLASSIFIED",
    "SANDBOX_UNKNOWN_OUTCOME_DETECTED",
    "SANDBOX_STALE_LOCK_DETECTED",
    "SANDBOX_STALE_LOCK_RECOVERED",
    "SANDBOX_SNAPSHOT_INVALID",
    "SANDBOX_RECONCILIATION_STARTED",
    "SANDBOX_MANUAL_REVIEW_CREATED",
)


def emit(events: List[Dict[str, Any]], event_type: str,
         run_id: str, timestamp, payload: Dict[str, Any]) -> None:
    """Append one immutable audit record (append-only, no mutation of prior)."""
    events.append({
        "event_type": event_type,
        "run_id": run_id,
        "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat")
        else str(timestamp),
        "payload": dict(payload),
    })
