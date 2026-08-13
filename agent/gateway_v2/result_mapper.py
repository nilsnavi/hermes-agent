"""V2 result + error mapping (Sprint 1.0.6).

OrchestrationResult → safe gateway response. Internal details (stack
traces, tool payload internals, approval ids, DB ids, event journals)
never reach the user. Error codes are structured; the gateway decides how
much jargon an ordinary user sees (production UX concern, not ours).
"""

from typing import Any, Dict, Optional

from agent.orchestrator import OrchestrationResult, StopReason

V2_OK = "V2_OK"
V2_NOT_ENABLED = "V2_NOT_ENABLED"
V2_NOT_ELIGIBLE = "V2_NOT_ELIGIBLE"
V2_BUDGET_EXCEEDED = "V2_BUDGET_EXCEEDED"
V2_APPROVAL_REQUIRED = "V2_APPROVAL_REQUIRED"
V2_MANUAL_REVIEW = "V2_MANUAL_REVIEW"
V2_EXECUTION_FAILED = "V2_EXECUTION_FAILED"
V2_CANCELLED = "V2_CANCELLED"
V2_INTERNAL_ERROR = "V2_INTERNAL_ERROR"

_STOP_REASON_CODES: Dict[StopReason, str] = {
    StopReason.COMPLETED: V2_OK,
    StopReason.APPROVAL_REQUIRED: V2_APPROVAL_REQUIRED,
    StopReason.MANUAL_REVIEW_REQUIRED: V2_MANUAL_REVIEW,
    StopReason.MAX_STEPS: V2_BUDGET_EXCEEDED,
    StopReason.MAX_TOOL_CALLS: V2_BUDGET_EXCEEDED,
    StopReason.MAX_REPLANS: V2_BUDGET_EXCEEDED,
    StopReason.MAX_FAILURES: V2_BUDGET_EXCEEDED,
    StopReason.RUNTIME_TIMEOUT: V2_BUDGET_EXCEEDED,
    StopReason.CANCELLED: V2_CANCELLED,
    StopReason.EXECUTION_FAILED: V2_EXECUTION_FAILED,
    StopReason.NO_PLAN: V2_EXECUTION_FAILED,
    StopReason.INVALID_PLAN: V2_EXECUTION_FAILED,
    StopReason.VERIFICATION_FAILED: V2_EXECUTION_FAILED,
}

_MESSAGES = {
    V2_OK: "completed",
    V2_NOT_ENABLED: "V2 runtime is not enabled",
    V2_NOT_ELIGIBLE: "request is not eligible for the V2 canary path",
    V2_BUDGET_EXCEEDED: "execution budget exceeded",
    V2_APPROVAL_REQUIRED: "approval required — execution paused",
    V2_MANUAL_REVIEW: "manual review required — no automatic execution",
    V2_EXECUTION_FAILED: "execution failed",
    V2_CANCELLED: "cancelled",
    V2_INTERNAL_ERROR: "internal error",
}


def code_for_stop_reason(reason: Optional[StopReason]) -> str:
    if reason is None:
        return V2_INTERNAL_ERROR
    return _STOP_REASON_CODES.get(reason, V2_INTERNAL_ERROR)


def _safe_output(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Keep ONLY the tool ``output`` of each completed step — no internals."""
    if not result:
        return None
    return {
        step_id: entry.get("output") if isinstance(entry, dict) else entry
        for step_id, entry in result.items()
    }


class V2ResultMapper:
    def map(self, request_id: str, result: Optional[OrchestrationResult]) -> Dict[str, Any]:
        """OrchestrationResult → user-safe response dict."""
        if result is None:
            return {"request_id": request_id, "ok": False, "code": V2_INTERNAL_ERROR,
                    "message": _MESSAGES[V2_INTERNAL_ERROR]}
        code = code_for_stop_reason(result.stop_reason)
        response: Dict[str, Any] = {
            "request_id": request_id,
            "ok": code == V2_OK,
            "code": code,
            "message": _MESSAGES.get(code, "unknown"),
            "status": result.status,
            "output": _safe_output(result.result) if code == V2_OK else None,
        }
        if code != V2_OK and result.error:
            response["reason"] = _first_line(result.error)  # no stack traces
        return response


def _first_line(text: str) -> str:
    """Keep the first meaningful line — stack traces stay internal."""
    meaningful = [
        line.strip()
        for line in str(text).splitlines()
        if line.strip() and not line.strip().startswith(
            ("File ", "Traceback", "  ", "\t", "line ", "^", "~")
        )
    ]
    return (meaningful[0] if meaningful else "execution failed")[:500]
