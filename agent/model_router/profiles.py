"""Logical model profiles (Sprint 0.5 §4).

A profile expresses *business intent* (fast chat, reports, deep reasoning,
coding) in model-selection terms.  It never carries credentials and never
names a concrete provider/model permanently — only preferences, capability
requirements and policy flags.  Provider/model resolution is the Router's
job, via the Provider Registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ModelProfile:
    """A logical capability/policy contract for routing.

    id:             canonical profile id (FAST, BALANCED, ...)
    description:    one-line purpose
    preferredCapabilities: capabilities the profile *prefers* (soft)
    requiredCapabilities:  capabilities a candidate model MUST have (hard)
    maxLatencyClass:      upper bound on latency class allowed
    maxCostClass:         upper bound on cost class allowed
    requiresToolCalling:  shortcut for requiredCapabilities=[TOOL_CALLING]
    requiresVision:       shortcut for VISION requirement
    preferredProviders:   ordered list of provider ids (soft preference)
    excludedProviders:    provider ids never used by this profile
    fallbackProfile:      lower-profile id for graceful degradation, or None
    allowUnknownHealth:   permit UNKNOWN-health candidates (legacy-proven only)
    maxOutputTokensDefault: default max_tokens cap hint
    enabled:              False disables the profile entirely
    """

    id: str
    description: str = ""
    preferredCapabilities: List[str] = field(default_factory=list)
    requiredCapabilities: List[str] = field(default_factory=list)
    maxLatencyClass: str = "NORMAL"
    maxCostClass: str = "HIGH"
    requiresTools: bool = False
    requiresVision: bool = False
    allowUnknownHealth: bool = False
    preferredProviders: List[str] = field(default_factory=list)
    excludedProviders: List[str] = field(default_factory=list)
    fallbackProfile: Optional[str] = None
    enabled: bool = True
    maxOutputTokensDefault: Optional[int] = None


# ── default catalog ──────────────────────────────────────────────────────

FAST = ModelProfile(
    id="FAST",
    description="cheap/fast requests — classification, extraction, simple chat",
    preferredCapabilities=["TEXT"],
    maxLatencyClass="NORMAL",
    maxCostClass="LOW",
    requiresTools=False,
    enabled=True,
)

BALANCED = ModelProfile(
    id="BALANCED",
    description="regular assistant work — reports, summarization, task reasoning",
    preferredCapabilities=["TEXT", "TOOL_CALLING"],
    maxLatencyClass="NORMAL",
    maxCostClass="MEDIUM",
    requiresTools=True,
    preferredProviders=["opencode", "deepseek"],
    fallbackProfile="FAST",
    enabled=True,
)

REASONING = ModelProfile(
    id="REASONING",
    description="complex analysis, planning, architecture",
    preferredCapabilities=["TEXT", "REASONING", "TOOL_CALLING"],
    maxLatencyClass="SLOW",
    maxCostClass="HIGH",
    requiresTools=True,
    preferredProviders=["opencode", "deepseek"],
    fallbackProfile="BALANCED",  # graceful degradation when no reasoning model
    enabled=True,
)

CODING = ModelProfile(
    id="CODING",
    description="code generation, debugging, repository work",
    requiredCapabilities=["CODING"],
    preferredCapabilities=["TEXT", "TOOL_CALLING", "CODING"],
    maxLatencyClass="SLOW",
    maxCostClass="HIGH",
    requiresTools=True,
    preferredProviders=["opencode"],
    fallbackProfile=None,  # no automatic degradation below coding quality
    enabled=True,
)

PROFILE_CATALOG: Dict[str, ModelProfile] = {p.id: p for p in (FAST, BALANCED, REASONING, CODING)}

DEFAULT_PROFILE_ID = "BALANCED"


def get_profile(profile_id: str) -> Optional[ModelProfile]:
    """Resolve a profile by id (case-insensitive). None when unknown."""
    if not profile_id:
        return None
    return PROFILE_CATALOG.get(profile_id.strip().upper())


def register_profile(profile: ModelProfile) -> None:
    """Register/override a profile at runtime (tests, operator config)."""
    PROFILE_CATALOG[profile.id.upper()] = profile


def unregister_profile(profile_id: str) -> None:
    PROFILE_CATALOG.pop((profile_id or "").upper(), None)


def all_profiles() -> List[ModelProfile]:
    return list(PROFILE_CATALOG.values())