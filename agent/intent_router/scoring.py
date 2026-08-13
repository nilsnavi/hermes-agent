"""Router scoring (Sprint 1.1 §31).

Score components (informative, not authoritative):

- intent_confidence — classifier confidence (bounded 0.0-1.0);
- capability_match — 1.0 if all required capabilities available else 0.0;
- risk_penalty — risk-class discount (LOW 1.0 / MEDIUM 0.85 /
  HIGH 0.6 / CRITICAL 0.0 / UNKNOWN 0.5);
- policy_priority — hard policy wins over score: a write intent is
  NOT canary-eligible regardless of score.

Final decisions are RULE-CONSTRAINED. The score is a *reporting*
component used by explain() and calibration analysis; it can never
override the rule engine.
"""

from typing import Any, Dict

from .models import IntentRisk, IntentType

_RISK_PENALTY = {
    IntentRisk.LOW: 1.0,
    IntentRisk.MEDIUM: 0.85,
    IntentRisk.HIGH: 0.6,
    IntentRisk.CRITICAL: 0.0,
    IntentRisk.UNKNOWN: 0.5,
}


def score_decision(
    *,
    intent: IntentType,
    confidence: float,
    capability_match: bool,
    risk: IntentRisk,
) -> Dict[str, Any]:
    """Compute the informational score components (rule-constrained)."""
    cap_score = 1.0 if capability_match else 0.0
    risk_score = _RISK_PENALTY.get(risk, 0.5)
    # Never let score overcome safety: unsafe intents cap the score.
    safety_cap = _safety_cap(intent)
    combined = confidence * cap_score * risk_score * safety_cap
    return {
        "intent_confidence": round(confidence, 4),
        "capability_match": cap_score,
        "risk_penalty": risk_score,
        "canary_history": 1.0,  # reserved; health gate handled in policy
        "policy_priority": safety_cap,
        "combined_score": round(combined, 4),
    }


def _safety_cap(intent: IntentType) -> float:
    """Hard cap: unsafe intents never score as canary candidates."""
    if intent in (IntentType.WRITE_ACTION, IntentType.DELETE_ACTION,
                  IntentType.SYSTEM_ACTION, IntentType.SCHEDULE_ACTION,
                  IntentType.APPROVAL_ACTION):
        return 0.0
    return 1.0
