"""Ordered routing rules (Sprint 1.1 §19) — the auditable rule list.

The policy engine evaluates in the order below; the first matching rule
defines the CANDIDATE route. Effective route is then constrained by
flags/health/mode gates. Rules are data — changing routing behaviour
means editing THIS list (and bumping RULES_VERSION), never scattering
logic. No self-modification: the router reads, never rewrites, rules.
"""

from typing import Dict, List

from .models import IntentType, ReasonCode, RoutingRecommendation

RULES_VERSION = "rules-v1"

#: (rule_id, description, intents, candidate, reasons)
#: intents None → applies to all.
RULES: List[Dict] = [
    {
        "id": "R1",
        "description": "explicit dangerous system action → DENY/LEGACY",
        "intents": [IntentType.SYSTEM_ACTION],
        "candidate": RoutingRecommendation.REQUIRE_APPROVAL,
        "reasons": [ReasonCode.WRITE_INTENT, ReasonCode.SYSTEM_LEGACY],
    },
    {
        "id": "R2",
        "description": "write/delete → never canary (DENY or approval path)",
        "intents": [IntentType.WRITE_ACTION, IntentType.DELETE_ACTION],
        "candidate": RoutingRecommendation.DENY,
        "reasons": [ReasonCode.WRITE_INTENT, ReasonCode.UNSAFE_SIDE_EFFECT],
    },
    {
        "id": "R3",
        "description": "schedule → legacy (scheduler migration later)",
        "intents": [IntentType.SCHEDULE_ACTION],
        "candidate": RoutingRecommendation.LEGACY,
        "reasons": [ReasonCode.SCHEDULE_LEGACY],
    },
    {
        "id": "R4",
        "description": "approval action → internal operations path (legacy)",
        "intents": [IntentType.APPROVAL_ACTION],
        "candidate": RoutingRecommendation.LEGACY,
        "reasons": [ReasonCode.APPROVAL_OPS_PATH],
    },
    {
        "id": "R5",
        "description": "unknown intent → legacy (never auto-canary)",
        "intents": [IntentType.UNKNOWN],
        "candidate": RoutingRecommendation.LEGACY,
        "reasons": [ReasonCode.UNKNOWN_INTENT],
    },
    {
        "id": "R6",
        "description": "read-only + canary eligible → V2_CANARY candidate",
        "intents": None,  # read-only families
        "candidate": RoutingRecommendation.V2_CANARY,
        "reasons": [ReasonCode.READ_ONLY_INTENT],
        "read_only_only": True,
    },
    {
        "id": "R7",
        "description": "read-only + shadow eligible → V2_SHADOW candidate",
        "intents": None,
        "candidate": RoutingRecommendation.V2_SHADOW,
        "reasons": [ReasonCode.READ_ONLY_INTENT],
        "read_only_only": True,
    },
    {
        "id": "R8",
        "description": "default → LEGACY (fail closed)",
        "intents": None,
        "candidate": RoutingRecommendation.LEGACY,
        "reasons": [ReasonCode.LEGACY_ONLY_POLICY],
    },
]


def list_rules() -> List[Dict]:
    """Auditable rules view (no secrets, no code)."""
    out = []
    for rule in RULES:
        out.append({
            "id": rule["id"],
            "description": rule["description"],
            "intents": (
                [i.value for i in rule["intents"]]
                if rule.get("intents") else None
            ),
            "candidate": rule["candidate"].value,
            "reasons": [r.value for r in rule["reasons"]],
            "read_only_only": rule.get("read_only_only", False),
        })
    return out
