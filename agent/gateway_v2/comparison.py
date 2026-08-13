"""Shadow comparison model (Sprint 1.0.6.1 §16-17).

A :class:`ShadowComparison` correlates one legacy request with its V2
shadow prediction — request_id only, NO prompt content, NO model
responses, NO secrets. ``mismatch_flags`` uses the fixed taxonomy below;
semantic answer comparison is intentionally NOT attempted yet (V2 does
not produce a production response in shadow mode).
"""

from typing import Any, Dict, List, Optional

# Mismatch taxonomy (§17).
NO_PLAN = "NO_PLAN"                     # no step_specs → planner could not build a plan
INVALID_PLAN = "INVALID_PLAN"           # plan failed validation
TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"   # a step tool is not in the request surface
WOULD_REQUIRE_WRITE = "WOULD_REQUIRE_WRITE"      # plan contains a non-READ_ONLY tool
WOULD_REQUIRE_APPROVAL = "WOULD_REQUIRE_APPROVAL"  # plan would pause at an approval gate
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"     # predicted budget would be exceeded
SHADOW_EXCEPTION = "SHADOW_EXCEPTION"   # shadow run raised / timed out
NO_MISMATCH = "NO_MISMATCH"             # legacy ok + shadow ok + plan valid

MISMATCH_CODES = frozenset({
    NO_PLAN, INVALID_PLAN, TOOL_NOT_ALLOWED, WOULD_REQUIRE_WRITE,
    WOULD_REQUIRE_APPROVAL, BUDGET_EXCEEDED, SHADOW_EXCEPTION, NO_MISMATCH,
})


class ShadowComparison:
    """Safe correlation record — no raw request content by construction."""

    __slots__ = (
        "request_id", "legacy_success", "shadow_success", "shadow_plan_valid",
        "shadow_stop_reason", "shadow_predicted_tools",
        "shadow_approval_required", "duration_ms", "mismatch_flags",
    )

    def __init__(
        self,
        request_id: str,
        legacy_success: bool,
        shadow_success: bool,
        shadow_plan_valid: bool = False,
        shadow_stop_reason: Optional[str] = None,
        shadow_predicted_tools: int = 0,
        shadow_approval_required: bool = False,
        duration_ms: float = 0.0,
        mismatch_flags: Optional[List[str]] = None,
    ) -> None:
        self.request_id = request_id
        self.legacy_success = legacy_success
        self.shadow_success = shadow_success
        self.shadow_plan_valid = shadow_plan_valid
        self.shadow_stop_reason = shadow_stop_reason
        self.shadow_predicted_tools = shadow_predicted_tools
        self.shadow_approval_required = shadow_approval_required
        self.duration_ms = round(duration_ms, 3)
        self.mismatch_flags = list(mismatch_flags or [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "legacy_success": self.legacy_success,
            "shadow_success": self.shadow_success,
            "shadow_plan_valid": self.shadow_plan_valid,
            "shadow_stop_reason": self.shadow_stop_reason,
            "shadow_predicted_tools": self.shadow_predicted_tools,
            "shadow_approval_required": self.shadow_approval_required,
            "duration_ms": self.duration_ms,
            "mismatch_flags": list(self.mismatch_flags),
        }


def build_comparison(
    request_id: str,
    shadow_report: Dict[str, Any],
    *,
    legacy_success: bool = True,
    duration_ms: float = 0.0,
) -> ShadowComparison:
    """Map a ShadowRunner report onto the mismatch taxonomy."""

    shadow_ok = bool(shadow_report.get("ok", shadow_report.get("eligible", False)))
    flags: List[str] = []
    reason = shadow_report.get("reason")
    issues = shadow_report.get("issues") or []

    if not shadow_ok and reason and str(reason).startswith("shadow error"):
        flags.append(SHADOW_EXCEPTION)
    elif shadow_report.get("timed_out"):
        flags.append(SHADOW_EXCEPTION)
    elif not shadow_report.get("plan_valid", shadow_report.get("valid", False)):
        joined_issues = " ".join(str(i) for i in (shadow_report.get("issues") or []))
        if "at least one step" in joined_issues or not joined_issues:
            flags.append(NO_PLAN)  # no step_specs → planner could not build a plan
        else:
            flags.append(INVALID_PLAN)
    elif shadow_report.get("denied_steps"):
        flags.append(TOOL_NOT_ALLOWED)  # a step was DENIED by risk policy
    elif shadow_report.get("would_require_write"):
        flags.append(WOULD_REQUIRE_WRITE)
    elif shadow_report.get("would_require_approval"):
        flags.append(WOULD_REQUIRE_APPROVAL)
    elif not legacy_success:
        flags.append(SHADOW_EXCEPTION)  # legacy failed; shadow is not the cause
    else:
        flags.append(NO_MISMATCH)

    return ShadowComparison(
        request_id=request_id,
        legacy_success=legacy_success,
        shadow_success=shadow_ok,
        shadow_plan_valid=bool(shadow_report.get("plan_valid",
                                                 shadow_report.get("valid", False))),
        shadow_stop_reason=shadow_report.get("stop_reason") or reason,
        shadow_predicted_tools=int(shadow_report.get("predicted_tool_calls", 0)),
        shadow_approval_required=bool(shadow_report.get("would_require_approval", False)),
        duration_ms=duration_ms,
        mismatch_flags=flags,
    )


__all__ = [
    "NO_PLAN", "INVALID_PLAN", "TOOL_NOT_ALLOWED", "WOULD_REQUIRE_WRITE",
    "WOULD_REQUIRE_APPROVAL", "BUDGET_EXCEEDED", "SHADOW_EXCEPTION",
    "NO_MISMATCH", "MISMATCH_CODES", "ShadowComparison", "build_comparison",
]
