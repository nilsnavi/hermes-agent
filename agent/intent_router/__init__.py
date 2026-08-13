"""Intent Router — Sprint 1.1 (OBSERVE / RECOMMEND ONLY).

Answers "which execution path fits this request?" WITHOUT being an
execution authority:

```
                   Request
                      |
                IntentRouter
                      |
      +---------------+---------------+
      |               |               |
 Classifier       Risk Engine    Capability Match
      |               |               |
      +---------------+---------------+
                      |
              RoutingDecision
                      |
            OBSERVE / RECOMMEND
                      |
           Gateway policy remains
             source of authority
```

Guarantees:

- CLASSIFY / SCORE / RECOMMEND / EXPLAIN only. Never EXECUTE / SWITCH /
  SEND / CALL TOOL. The gateway adapter's deny-by-default mechanism
  stays the only authority.
- Deterministic rule-based classifier (RU+EN) — no LLM by default.
- candidate_route vs effective_route are separate (§35).
- Fail closed: any router exception → LEGACY + ROUTER_ERROR (§20).
- UNKNOWN intent → LEGACY (§21). Unsafe intents never V2_CANARY (§75).
- Events carry whitelisted scalars only — never the prompt (§40/§83).
- Stdlib-only, no gateway/scheduler/provider imports at module level.

Feature flags (defaults: disabled / off):

    HERMES_INTENT_ROUTER_ENABLED=false
    HERMES_INTENT_ROUTER_MODE=off   # off | observe | shadow_decision
"""

from .capabilities import CapabilityRegistry
from .classifier import (
    IntentClassifier,
    RuleBasedIntentClassifier,
)
from .evaluation import IntentRouterEvaluator, build_dataset, dataset_stats
from .exceptions import IntentRouterError
from .explain import explain, explain_rich
from .models import (
    ExpectedSideEffect,
    IntentRisk,
    IntentRoutingDecision,
    IntentType,
    RequestIntentFeatures,
    RouterMode,
    RouterStatus,
    RoutingRecommendation,
)
from .policy import RouterPolicy
from .router import (
    IntentRouter,
    ROUTER_VERSION,
    RouterEvent,
    RouterStats,
    parse_mode,
    read_router_flags,
)
from .rules import RULES, RULES_VERSION, list_rules

__all__ = [
    "IntentRouter",
    "IntentRouterError",
    "IntentRouterEvaluator",
    "RouterPolicy",
    "RouterMode",
    "RouterStatus",
    "RouterEvent",
    "RouterStats",
    "IntentType",
    "IntentRisk",
    "ExpectedSideEffect",
    "RoutingRecommendation",
    "IntentRoutingDecision",
    "RequestIntentFeatures",
    "IntentClassifier",
    "RuleBasedIntentClassifier",
    "CapabilityRegistry",
    "build_dataset",
    "dataset_stats",
    "explain",
    "explain_rich",
    "parse_mode",
    "read_router_flags",
    "ROUTER_VERSION",
    "RULES",
    "RULES_VERSION",
    "list_rules",
]
