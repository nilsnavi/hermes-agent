"""Stable JSON serialization for the operations layer (Sprint 1.0.6.3).

Rules:

- Keys are sorted, enums serialize as ``.value``, timestamps stay
  ISO-8601 strings → STABLE schema for automation (``--json``).
- No raw payloads ever: the event summary whitelist maps event types
  to the exact scalar fields an operator may see. Everything else is
  dropped.
"""

import json
from typing import Any, Dict, List, Optional

# Whitelist mapping: event_type -> {payload key -> output field}.
# Only whitelisted scalar fields are surfaced in operator views.
# Hash columns are surfaced by the store layer, not payload_json.
EVENT_SUMMARY_WHITELIST: Dict[str, Dict[str, str]] = {
    "RUN_CREATED": {"model_profile": "model_profile", "task_type": "task_type"},
    "STATE_CHANGED": {"from_status": "from_status", "to_status": "to_status"},
    "PLAN_CREATED": {},
    "STEP_STARTED": {"step": "step_id", "plan_id": "plan_id", "name": "name"},
    "STEP_WAITING_APPROVAL": {"step": "step_id", "plan_id": "plan_id"},
    "STEP_APPROVED": {"step": "step_id", "approval": "approval_id"},
    "STEP_REJECTED": {"step": "step_id", "approval": "approval_id"},
    "TOOL_STARTED": {"step": "step_id", "tool": "tool_name",
                     "input_hash": "input_hash", "idempotency_key": "idempotency_key"},
    "TOOL_COMPLETED": {"step": "step_id", "tool": "tool_name",
                       "output_hash": "output_hash", "duration_ms": "duration_ms"},
    "TOOL_FAILED": {"step": "step_id", "tool": "tool_name",
                    "error_class": "error_class", "status": "status"},
    "EXECUTION_COMPLETED": {"steps": "steps"},
    "ORCHESTRATION_STARTED": {},
    "ORCHESTRATION_RESUMED": {},
    "ORCHESTRATION_STOPPED": {"stop_reason": "stop_reason", "steps": "steps",
                              "tool_calls": "tool_calls", "failures": "failures"},
    "BUDGET_EXCEEDED": {"limit": "limit"},
    "CANCELLATION_REQUESTED": {"reason": "reason"},
    "REPLAN_REQUESTED": {"reason": "reason"},
    "REPLAN_SKIPPED": {"reason": "reason"},
    "RECOVERY_SCANNED": {"disposition": "disposition", "action": "action"},
    "RECOVERY_CLASSIFIED": {"disposition": "disposition", "action": "action"},
    "RECOVERY_RESUMED": {"reason": "reason"},
    "RECOVERY_WAITING": {"reason": "reason"},
    "RECOVERY_MANUAL_REVIEW": {"reason": "reason", "run_status": "run_status"},
    "RECOVERY_VERIFIED": {"reason": "reason"},
    "RECOVERY_REVIEWED": {"decision": "decision"},
    "APPROVAL_VIEWED": {"approval": "approval_id", "operator": "operator_id",
                        "decision_source": "decision_source"},
    "APPROVAL_APPROVED": {"approval": "approval_id", "step": "step_id",
                          "operator": "operator_id",
                          "decision_source": "decision_source",
                          "reason_code": "reason_code"},
    "APPROVAL_REJECTED": {"approval": "approval_id", "step": "step_id",
                          "operator": "operator_id",
                          "decision_source": "decision_source",
                          "reason_code": "reason_code"},
    "APPROVAL_EXPIRED": {"approval": "approval_id", "step": "step_id",
                         "operator": "operator_id",
                         "decision_source": "decision_source",
                         "reason_code": "reason_code"},
}


def summarize_event_payload(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Whitelist projection of one event payload (no raw content)."""
    mapping = EVENT_SUMMARY_WHITELIST.get(event_type, {})
    out: Dict[str, Any] = {}
    for key, field in mapping.items():
        if key in payload and payload[key] is not None:
            out[field] = payload[key]
    return out


def to_json(value: Any) -> str:
    """Stable JSON: sorted keys, enums as values, no raw payloads."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                      default=_default)


def _default(obj: Any) -> Any:
    from enum import Enum

    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def dto_list_to_json(dtos: List[Any]) -> str:
    return to_json([d.to_dict() for d in dtos])


def sanitize_note(note: Optional[str], max_len: int = 200) -> Optional[str]:
    """Short, redacted operator note. Never accept arbitrary long text."""
    if note is None:
        return None
    note = " ".join(str(note).split())
    if len(note) > max_len:
        note = note[:max_len] + "…"
    return note or None
