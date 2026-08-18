"""Capability Router metrics (Sprint 1.3.0 §29, §30).

Aggregates ONLY — no raw prompts, no authorization, no tool args ever
enter the counters. Two families:

- decision counters (§29): capability_router_decisions / allowed /
  legacy / denied / mismatch — by intent, capability, tool, reason.
- comparison metrics (§30): decision_match, route_mismatch,
  tool_mismatch, reason_mismatch, subtype_mismatch. Acceptance for
  existing V2-eligible requests: route mismatch = 0, tool mismatch = 0.

Latency ring is bounded (1000) and in-memory — no persistence.
"""

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


def _pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))
    return round(s[idx], 3)


@dataclass
class CapabilityRouterStats:
    """In-memory capability-router counters (§29/§30)."""

    decisions: int = 0
    allowed: int = 0       # route V2
    legacy: int = 0        # route LEGACY
    denied: int = 0        # route DENY (reserved; must stay 0 in 1.3.x)
    errors: int = 0
    # Sprint 1.3.1 §20 — policy metrics (canonical names).
    policy_decisions_total: int = 0
    policy_allow_v2: int = 0
    policy_legacy: int = 0
    policy_deny: int = 0
    policy_fail_closed: int = 0   # exceptions → LEGACY/DENY (§8/§19)
    # comparison metrics (§30)
    decision_match: int = 0
    route_mismatch: int = 0
    tool_mismatch: int = 0
    reason_mismatch: int = 0
    subtype_mismatch: int = 0
    # breakdowns (§29) — aggregates only
    by_intent: Counter = field(default_factory=Counter)
    by_capability: Counter = field(default_factory=Counter)
    by_tool: Counter = field(default_factory=Counter)
    by_reason: Counter = field(default_factory=Counter)
    by_route: Counter = field(default_factory=Counter)
    by_policy_version: Counter = field(default_factory=Counter)
    # latency ring (bounded, in-memory)
    _durations: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    _count: int = 0
    _sum: float = 0.0

    def record(
        self,
        route: str,
        intent: str,
        capability: Optional[str],
        tool: Optional[str],
        reason: Optional[str],
        duration_ms: float,
        *,
        has_legacy: bool = False,
        decision_match: Optional[bool] = None,
        tool_match: Optional[bool] = None,
        reason_match: Optional[bool] = None,
        subtype_match: Optional[bool] = None,
        fail_closed: bool = False,
        policy_version: str = "cap-policy-v1",
    ) -> None:
        self.decisions += 1
        self.policy_decisions_total += 1
        self.by_route[route] += 1
        self.by_intent[intent] += 1
        self.by_policy_version[policy_version] += 1
        if capability:
            self.by_capability[capability] += 1
        if tool:
            self.by_tool[tool] += 1
        if reason:
            self.by_reason[reason] += 1
        if route == "V2":
            self.allowed += 1
            self.policy_allow_v2 += 1
        elif route == "DENY":
            self.denied += 1
            self.policy_deny += 1
        else:
            self.legacy += 1
            self.policy_legacy += 1
        if fail_closed:
            self.policy_fail_closed += 1
        self._durations.append(float(duration_ms))
        self._sum += float(duration_ms)
        self._count += 1
        # comparison (§30) — mirrors the CapabilityRouteDecision match
        # flags (normalized tool/reason), only when a legacy decision
        # was available.
        if not has_legacy:
            return
        if decision_match is True:
            self.decision_match += 1
        else:
            self.route_mismatch += 1
        if tool_match is not True:
            self.tool_mismatch += 1
        if reason_match is not True:
            self.reason_mismatch += 1
        if subtype_match is not True:
            self.subtype_mismatch += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decisions": self.decisions,
            "allowed": self.allowed,
            "legacy": self.legacy,
            "denied": self.denied,
            "errors": self.errors,
            "policy": {
                "policy_decisions_total": self.policy_decisions_total,
                "policy_allow_v2": self.policy_allow_v2,
                "policy_legacy": self.policy_legacy,
                "policy_deny": self.policy_deny,
                "policy_fail_closed": self.policy_fail_closed,
            },
            "comparison": {
                "decision_match": self.decision_match,
                "route_mismatch": self.route_mismatch,
                "tool_mismatch": self.tool_mismatch,
                "reason_mismatch": self.reason_mismatch,
                "subtype_mismatch": self.subtype_mismatch,
            },
            "by_intent": dict(self.by_intent),
            "by_capability": dict(self.by_capability),
            "by_tool": dict(self.by_tool),
            "by_reason": dict(self.by_reason),
            "by_route": dict(self.by_route),
            "by_policy_version": dict(self.by_policy_version),
            "duration_ms": {
                "count": self._count,
                "sum": round(self._sum, 3),
                "p50": _pct(list(self._durations), 50),
                "p95": _pct(list(self._durations), 95),
            },
        }


__all__ = ["CapabilityRouterStats"]
