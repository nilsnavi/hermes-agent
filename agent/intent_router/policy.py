"""Router policy (Sprint 1.1 §26-29, §32-35).

Policy answers: given a classification + capability surface + live
runtime health + router flags, what is the CANDIDATE route and what
is the EFFECTIVE route?

Rules (ordered, first match wins):

1. Router exception / unknown → LEGACY (fail closed).
2. UNKNOWN intent → LEGACY.
3. write/delete/system/schedule/approval intent:
   - delete → candidate DENY (critical, irreversible);
   - system → candidate DENY or REQUIRE_APPROVAL (high);
   - write/schedule/approval → candidate REQUIRE_APPROVAL
     (approval does NOT permit execution — execution policy still
     governs; canary never executes writes);
   - effective route for ALL unsafe families: LEGACY.
4. read-only intents (§35): candidate_route is the IDEAL route —
   canary when every canary gate except the allowlist passes;
   else shadow when the shadow gate passes (shadow is broader, §28,
   and never needs a capability — it does not execute tools);
   else LEGACY.
5. effective_route (§34-35, §61): the candidate AND the EXPLICIT
   gates — canary allowlist, healthy health, and the canary flag
   kill switch. A non-allowlisted read stays LEGACY effective even
   when the candidate is V2_CANARY (MUST-HAVE #3).

The gateway adapter remains the ONLY authority: this module only
produces recommendations. Nothing here executes, switches, sends or
calls tools.
"""

from typing import Any, Dict, List, Optional

from .capabilities import CapabilityRegistry
from .classifier import Classification
from .models import (
    ExpectedSideEffect,
    IntentRisk,
    IntentType,
    ReasonCode,
    RoutingRecommendation,
)
from .scoring import score_decision

#: Minimum confidence for a V2_CANARY candidate (§27).
CANARY_CONFIDENCE_THRESHOLD = 0.7
#: Minimum confidence for a V2_SHADOW candidate (§28).
SHADOW_CONFIDENCE_THRESHOLD = 0.5

#: Allowed risk classes for a V2_CANARY candidate (§27).
CANARY_ALLOWED_RISKS = (IntentRisk.LOW, IntentRisk.MEDIUM)


class RouterPolicy:
    """Rule-constrained routing policy (Sprint 1.1)."""

    VERSION = "policy-v1"

    def __init__(
        self,
        capabilities: Optional[CapabilityRegistry] = None,
        health_gate: bool = True,
        allowlist_fn=None,
    ) -> None:
        self._capabilities = capabilities or CapabilityRegistry()
        self._health_gate = health_gate
        # allowlist_fn(features) -> bool (explicit canary eligibility).
        self._allowlist = allowlist_fn or (lambda features: features.internal)

    # ── main decision ────────────────────────────────────────────────

    def decide(
        self,
        classification: Classification,
        features,
        *,
        flags: Optional[Dict[str, bool]] = None,
        health: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return the decision fields (candidate/effective/reasons)."""
        flags = flags or {}
        health = health or {}

        required = self._capabilities.required_for(classification.intent)
        cap_ok = self._capabilities.capabilities_satisfied(required)
        gap = self._capabilities.capability_gap(required)

        score = score_decision(
            intent=classification.intent,
            confidence=classification.confidence,
            capability_match=cap_ok,
            risk=classification.risk,
        )

        # 1) unsafe families (never canary, candidate varies).
        if classification.intent in (
            IntentType.WRITE_ACTION, IntentType.DELETE_ACTION,
            IntentType.SYSTEM_ACTION, IntentType.SCHEDULE_ACTION,
            IntentType.APPROVAL_ACTION,
        ):
            return self._unsafe_decision(
                classification, features, flags, required, score, gap
            )

        # 2) unknown → LEGACY (§21).
        if classification.intent is IntentType.UNKNOWN:
            return self._legacy_decision(
                classification, [ReasonCode.UNKNOWN_INTENT.value],
                required, score, gap,
            )

        # 3) read-only intents → candidate canary/shadow (§35).
        # candidate_route is the IDEAL route: the allowlist is NOT part
        # of the candidate — it gates the EFFECTIVE route (MUST-HAVE #3).
        canary_candidate = self._canary_candidate(
            classification, flags, health, cap_ok
        )
        shadow_candidate = self._shadow_candidate(
            classification, flags, health
        )

        candidate = RoutingRecommendation.LEGACY
        reasons: List[str] = []
        if canary_candidate:
            candidate = RoutingRecommendation.V2_CANARY
            reasons.append(ReasonCode.READ_ONLY_INTENT.value)
        elif shadow_candidate:
            candidate = RoutingRecommendation.V2_SHADOW
            reasons.append(ReasonCode.READ_ONLY_INTENT.value)
        else:
            reasons.append(self._read_only_legacy_reason(
                classification, features, flags, health, cap_ok, gap
            ))

        # canary_eligible / shadow_eligible = FULL gate (candidate AND
        # allowlist AND healthy AND canary-flag kill switch §34).
        canary_eligible = (
            canary_candidate
            and self._allowlist(features)
            and self._health_is_healthy(health)
        )
        shadow_eligible = (
            shadow_candidate
            and bool(flags.get("canary"))   # §34 kill switch
            and self._allowlist(features)
            and self._health_is_healthy(health)
        )

        effective = candidate
        if (candidate is RoutingRecommendation.V2_CANARY
                and not canary_eligible):
            effective = RoutingRecommendation.LEGACY
        elif (candidate is RoutingRecommendation.V2_SHADOW
                and not shadow_eligible):
            effective = RoutingRecommendation.LEGACY
        if effective.value != candidate.value:
            reasons.append(self._effective_gate_reason(
                candidate, features, flags, health
            ))

        return self._pack(
            classification, features, candidate, effective, reasons,
            required, score, gap, canary_eligible, shadow_eligible, flags,
        )

    # ── internals ────────────────────────────────────────────────────

    def _unsafe_decision(self, classification, features, flags,
                         required, score, gap) -> Dict[str, Any]:
        intent = classification.intent
        reasons = [ReasonCode.WRITE_INTENT.value]
        if intent is IntentType.DELETE_ACTION:
            candidate = RoutingRecommendation.DENY
            reasons.append(ReasonCode.CRITICAL_RISK.value)
        elif intent is IntentType.SYSTEM_ACTION:
            candidate = RoutingRecommendation.REQUIRE_APPROVAL
            reasons.append(ReasonCode.LEGACY_ONLY_POLICY.value)
        elif intent is IntentType.APPROVAL_ACTION:
            candidate = RoutingRecommendation.REQUIRE_APPROVAL
            reasons.append(ReasonCode.APPROVAL_OPS_PATH.value)
        else:  # write / schedule
            candidate = RoutingRecommendation.REQUIRE_APPROVAL
            reasons.append(ReasonCode.LEGACY_ONLY_POLICY.value)

        # Effective route is ALWAYS legacy for unsafe families.
        effective = RoutingRecommendation.LEGACY
        if candidate is RoutingRecommendation.DENY:
            effective = RoutingRecommendation.DENY
        return self._pack(
            classification, features, candidate, effective, reasons,
            required, score, gap, False, False, flags,
            approval_required=True,
        )

    def _canary_candidate(
        self, classification, flags, health, cap_ok: bool
    ) -> bool:
        """§27 candidate gates (allowlist NOT included — it gates the
        EFFECTIVE route per §35 / MUST-HAVE #3)."""
        if not flags.get("canary"):
            return False
        if not cap_ok:
            return False
        if classification.risk not in CANARY_ALLOWED_RISKS:
            return False
        if classification.confidence < CANARY_CONFIDENCE_THRESHOLD:
            return False
        if classification.expected_side_effect not in (
            ExpectedSideEffect.NONE, ExpectedSideEffect.READ_ONLY
        ):
            return False
        if not self._health_allows_candidate(health):
            return False
        return True

    def _shadow_candidate(self, classification, flags, health) -> bool:
        """§28: shadow is broader but still explicit-only in production.
        Candidate-level gate only (no capability, no allowlist)."""
        if not flags.get("shadow"):
            return False
        if classification.risk is IntentRisk.CRITICAL:
            return False
        if classification.confidence < SHADOW_CONFIDENCE_THRESHOLD:
            return False
        if classification.expected_side_effect not in (
            ExpectedSideEffect.NONE, ExpectedSideEffect.READ_ONLY
        ):
            return False
        # shadow never needs capability: it does not execute tools.
        return self._health_allows_candidate(health)

    def _health_allows_candidate(self, health: Dict[str, Any]) -> bool:
        """§61: candidate may be V2_CANARY while HEALTHY or DEGRADED;
        UNHEALTHY/UNKNOWN → candidate LEGACY too."""
        return health.get("status", "unknown") in ("healthy", "degraded")

    def _health_is_healthy(self, health: Dict[str, Any]) -> bool:
        """Effective V2 requires HEALTHY runtime (§61)."""
        return health.get("status", "unknown") == "healthy"

    def _effective_gate_reason(
        self, candidate, features, flags, health
    ) -> str:
        if candidate is RoutingRecommendation.V2_CANARY:
            if not self._allowlist(features):
                return ReasonCode.CANARY_ALLOWLIST_REQUIRED.value
            if not self._health_is_healthy(health):
                return ReasonCode.HEALTH_GATE.value
        if candidate is RoutingRecommendation.V2_SHADOW:
            if not flags.get("canary"):
                return ReasonCode.CANARY_DISABLED.value  # §34 kill switch
            if not self._allowlist(features):
                return ReasonCode.CANARY_ALLOWLIST_REQUIRED.value
            if not self._health_is_healthy(health):
                return ReasonCode.HEALTH_GATE.value
        return ReasonCode.LEGACY_ONLY_POLICY.value

    def _read_only_legacy_reason(
        self, classification, features, flags, health, cap_ok, gap
    ) -> str:
        if not cap_ok:
            return ReasonCode.CAPABILITY_MISSING.value
        if not flags.get("canary") and not flags.get("shadow"):
            return ReasonCode.MODE_OFF.value
        if not flags.get("canary"):
            return ReasonCode.CANARY_DISABLED.value
        if classification.risk not in CANARY_ALLOWED_RISKS:
            return ReasonCode.CRITICAL_RISK.value
        if classification.confidence < CANARY_CONFIDENCE_THRESHOLD:
            return ReasonCode.LOW_CONFIDENCE.value
        if self._health_gate and not self._health_is_healthy(health):
            return ReasonCode.HEALTH_GATE.value
        if not self._allowlist(features):
            return ReasonCode.CANARY_ALLOWLIST_REQUIRED.value
        return ReasonCode.LEGACY_ONLY_POLICY.value

    def _legacy_decision(self, classification, reasons, required,
                         score, gap) -> Dict[str, Any]:
        return self._pack(
            classification, None, RoutingRecommendation.LEGACY,
            RoutingRecommendation.LEGACY, reasons, required, score,
            gap, False, False, {},
        )

    def _pack(self, classification, features, candidate, effective,
              reasons, required, score, gap, canary_eligible,
              shadow_eligible, flags, approval_required=False) -> Dict[str, Any]:
        return {
            "intent": classification.intent.value,
            "risk": classification.risk.value,
            "expected_side_effect": classification.expected_side_effect.value,
            "candidate_route": candidate.value,
            "effective_route": effective.value,
            "recommended_route": effective.value,
            "confidence": classification.confidence,
            "reason_codes": list(dict.fromkeys(reasons)),
            "required_capabilities": list(required),
            "capability_gap": gap,
            "eligible_tools": self._tools_for(required, cap_ok=True)
                if self._capabilities.capabilities_satisfied(required)
                else [],
            "approval_required": approval_required,
            "canary_eligible": canary_eligible,
            "shadow_eligible": shadow_eligible,
            "fallback_route": RoutingRecommendation.LEGACY.value,
            "score": score,
        }

    def _tools_for(self, required, cap_ok: bool) -> List[str]:
        tools: List[str] = []
        for cap in required:
            if self._capabilities.has(cap):
                try:
                    tools.extend(self._capabilities.tools_for_capability(cap))
                except Exception:
                    pass
        return sorted(set(tools))


__all__ = [
    "RouterPolicy",
    "CANARY_CONFIDENCE_THRESHOLD",
    "SHADOW_CONFIDENCE_THRESHOLD",
    "CANARY_ALLOWED_RISKS",
]
