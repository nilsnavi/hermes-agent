"""Decision explainability (Sprint 1.1 §53).

Safe, human-readable explanation of a routing decision. Never dumps
raw rules, never includes prompts, arguments or secrets.
"""

from typing import Any, Dict, List

from .models import IntentRoutingDecision, ReasonCode

_HUMAN_REASONS = {
    ReasonCode.READ_ONLY_INTENT.value: "read-only intent",
    ReasonCode.WRITE_INTENT.value: "write/unsafe intent",
    ReasonCode.UNKNOWN_INTENT.value: "intent not recognized",
    ReasonCode.CRITICAL_RISK.value: "critical risk",
    ReasonCode.CAPABILITY_MISSING.value: "required capability missing",
    ReasonCode.CANARY_ALLOWLIST_REQUIRED.value:
        "not in the canary allowlist",
    ReasonCode.TOOL_NOT_AVAILABLE.value: "tool not available",
    ReasonCode.APPROVAL_REQUIRED.value: "approval required",
    ReasonCode.LEGACY_ONLY_POLICY.value: "legacy-only by policy",
    ReasonCode.LOW_CONFIDENCE.value: "low confidence",
    ReasonCode.UNSAFE_SIDE_EFFECT.value: "unsafe side effect",
    ReasonCode.ROUTER_ERROR.value: "router error",
    ReasonCode.HEALTH_GATE.value: "runtime health gate",
    ReasonCode.CANARY_DISABLED.value: "canary disabled",
    ReasonCode.SHADOW_DISABLED.value: "shadow disabled",
    ReasonCode.MODE_OFF.value: "router mode off",
    ReasonCode.SCHEDULE_LEGACY.value: "scheduling stays legacy",
    ReasonCode.SYSTEM_LEGACY.value: "system actions stay legacy",
    ReasonCode.APPROVAL_OPS_PATH.value:
        "approval actions use the internal operations path",
    ReasonCode.DENY_BY_POLICY.value: "denied by policy",
}


def explain(decision: IntentRoutingDecision) -> str:
    """One-line safe explanation of the decision."""
    route = decision.effective_route
    intent = decision.intent
    reasons = [_human(code) for code in decision.reason_codes]
    reasons_text = ", ".join(reasons) if reasons else "no reason recorded"

    if decision.candidate_route != decision.effective_route:
        return (
            f"{route.upper()} (candidate {decision.candidate_route}) "
            f"because {reasons_text} — intent {intent}"
        )
    return (
        f"{route.upper()} because {reasons_text} — intent {intent}"
    )


def explain_rich(decision: IntentRoutingDecision) -> Dict[str, Any]:
    """Structured safe explanation (no raw rules, no content)."""
    return {
        "effective_route": decision.effective_route,
        "candidate_route": decision.candidate_route,
        "intent": decision.intent,
        "risk": decision.risk,
        "confidence": decision.confidence,
        "reason_codes": list(decision.reason_codes),
        "reasons": [_human(code) for code in decision.reason_codes],
        "required_capabilities": list(decision.required_capabilities),
        "eligible_tools": list(decision.eligible_tools),
        "approval_required": decision.approval_required,
        "fallback_route": decision.fallback_route,
    }


def _human(code: str) -> str:
    return _HUMAN_REASONS.get(code, code)


__all__ = ["explain", "explain_rich"]
