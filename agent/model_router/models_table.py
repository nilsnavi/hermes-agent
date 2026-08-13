"""Model capability metadata (Sprint 0.5 §5, §6).

ModelDefinition holds *verified* capability facts only.  An unverified
capability is simply not listed (DoD: never invent capability).  The router
is conservative: capabilities gate eligibility, so an unlisted capability
makes a model ineligible for profiles that require it — which is the
correct behaviour until a probe verifies otherwise.

The current production model (opencode / deepseek-v4-flash-free) is
present, verified by live health probe (Sprint 0.4 integration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


class ModelCapability:
    TEXT = "TEXT"
    TOOL_CALLING = "TOOL_CALLING"
    VISION = "VISION"
    REASONING = "REASONING"
    CODING = "CODING"
    LONG_CONTEXT = "LONG_CONTEXT"
    JSON_STRUCTURED_OUTPUT = "JSON_STRUCTURED_OUTPUT"

    ALL = (TEXT, TOOL_CALLING, VISION, REASONING, CODING, LONG_CONTEXT, JSON_STRUCTURED_OUTPUT)


# Cost / latency classes (ordinal order: higher idx = better)
COST_ORDER = {"FREE": 4, "LOW": 3, "MEDIUM": 2, "HIGH": 1, "UNKNOWN": 0}
LATENCY_ORDER = {"FAST": 3, "NORMAL": 2, "SLOW": 1, "UNKNOWN": 0}


@dataclass(frozen=True)
class ModelDefinition:
    """Immutable metadata entry for one provider/model pair."""

    provider: str
    model: str
    aliases: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    contextWindow: Optional[int] = None
    costClass: str = "UNKNOWN"
    latencyClass: str = "UNKNOWN"
    enabled: bool = True
    verified: bool = False
    lastVerifiedAt: Optional[str] = None

    def has_all(self, required: List[str]) -> bool:
        caps = set(self.capabilities)
        return all(c in caps for c in (required or []))

    def has_any(self, preferred: List[str]) -> List[str]:
        caps = set(self.capabilities)
        return [c for c in (preferred or []) if c in caps]


# ── verified registry ─────────────────────────────────────────────────────
# verified=True only for models whose live probe returned 200 and whose
# tool-calling path is exercised by the production runtime.
MODEL_REGISTRY: Dict[str, List[ModelDefinition]] = {
    "opencode": [
        ModelDefinition(
            provider="opencode",
            model="deepseek-v4-flash-free",
            capabilities=["TEXT", "TOOL_CALLING"],
            contextWindow=94000,
            costClass="FREE",
            latencyClass="FAST",
            verified=True,
            lastVerifiedAt="2026-08-08T11:00:00+03:00",
        ),
    ],
    "deepseek": [
        ModelDefinition(
            provider="deepseek",
            model="deepseek-chat",
            aliases=["deepseek-v4", "deepseek-v4-flash"],
            capabilities=["TEXT", "TOOL_CALLING"],
            contextWindow=64000,
            costClass="LOW",
            latencyClass="NORMAL",
            verified=True,
            lastVerifiedAt="2026-08-08T11:00:00+03:00",
        ),
    ],
}


def models_for_provider(provider: str) -> List[ModelDefinition]:
    return list(MODEL_REGISTRY.get(provider, []))


def register_model(definition: ModelDefinition) -> None:
    lst = MODEL_REGISTRY.setdefault(definition.provider, [])
    lst[:] = [m for m in lst if m.model != definition.model] + [definition]


def find_model(provider: str, model: str) -> Optional[ModelDefinition]:
    for m in models_for_provider(provider):
        if m.model == model or model in m.aliases:
            return m
    return None


def all_models() -> List[ModelDefinition]:
    out: List[ModelDefinition] = []
    for lst in MODEL_REGISTRY.values():
        out.extend(lst)
    return out