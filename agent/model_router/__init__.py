"""Model Router V1 + Logical Model Profiles (Sprint 0.5).

Layered architecture (never inverted):

    Model Router (agent/model_router)
            ↓
    Provider Registry (agent/provider_registry)   ← Sprint 0.4

Model Router owns: profiles, model capability metadata, deterministic
selection, unsupported-model guard, shadow comparison.
Provider Registry owns: provider health, auth, availability, circuit,
routing eligibility.

Sprint 0.5 is SHADOW ONLY: routed decisions never execute and never
change the production selection path (legacy runtime stays untouched).

Feature flags (env, all default FALSE → 100% legacy behaviour):

    HERMES_PROVIDER_REGISTRY_V2   Provider Registry observability (Sprint 0.4)
    HERMES_MODEL_ROUTER_V2        Model Router availability
    HERMES_MODEL_ROUTER_SHADOW    shadow-comparison logging for route decisions

Flag matrix:
    reg=false, router=false  → legacy unchanged            (MODE A)
    reg=true,  router=false  → registry observability only (MODE B)
    reg=true,  router=true   → router available, shadow     (MODE C)
    production automatic model selection: NOT wired in this sprint.

Reserved metric names (no Prometheus stack yet — events/status only, §23):

    hermes_model_routes_total
    hermes_model_route_failures_total
    hermes_model_shadow_mismatch_total
    hermes_model_profile_routes_total
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from agent.provider_registry import ProviderRegistry

from .models_table import (
    ModelCapability,
    ModelDefinition,
    all_models,
    find_model,
    models_for_provider,
    register_model,
)
from .profiles import DEFAULT_PROFILE_ID, ModelProfile, all_profiles, get_profile
from .router import (
    FallbackCandidate,
    ModelRouteDecision,
    ModelRouter,
    ProfileError,
    shadow_compare,
)

__all__ = [
    "ModelCapability",
    "ModelDefinition",
    "ModelProfile",
    "ModelRouteDecision",
    "ModelRouter",
    "FallbackCandidate",
    "ProfileError",
    "shadow_compare",
    "get_profile",
    "all_profiles",
    "all_models",
    "find_model",
    "models_for_provider",
    "register_model",
    "router_v2_enabled",
    "shadow_enabled",
]

_DEFAULT_PROFILE = "BALANCED"


def router_v2_enabled() -> bool:
    """HERMES_MODEL_ROUTER_V2 (default false)."""
    return os.environ.get("HERMES_MODEL_ROUTER_V2", "false").strip().lower() == "true"


def shadow_enabled() -> bool:
    """HERMES_MODEL_ROUTER_SHADOW (default false)."""
    return os.environ.get("HERMES_MODEL_ROUTER_SHADOW", "false").strip().lower() == "true"


def get_router(registry: Optional[ProviderRegistry] = None) -> ModelRouter:
    """Thread-local router handle. Router itself is stateless/read-only."""
    return ModelRouter(registry=registry)