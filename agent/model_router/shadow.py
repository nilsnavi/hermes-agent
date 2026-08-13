"""Shadow mode (Sprint 0.5 §15): legacy runtime vs Model Router.

Shadow comparator is *pure calculation* — it never touches the runtime
request path and never reads prompt content.  Used by tests, CLI
(`shadow-status`) and any future integration point.
"""

from __future__ import annotations

import os
from typing import Optional

from agent.provider_registry.events import emit

from . import get_router  # noqa: F401  (re-exported for callers)
from .models_table import models_for_provider
from .profiles import DEFAULT_PROFILE_ID
from .router import ModelRouter, ModelRouteDecision

_TRUTHY = ("1", "true", "yes", "on")


def shadow_compare(
    router: ModelRouter,
    legacy_provider: str,
    legacy_model: str,
    profile: str = DEFAULT_PROFILE_ID,
) -> ModelRouteDecision:
    """Compute WHAT WOULD V2 SELECT without affecting the actual request.

    Emits ``model.route.shadow_compare`` when the flag is enabled; never
    includes prompt content, tokens or credentials.
    """
    decision = router.route_model(profile=profile)
    same = (
        decision.provider == legacy_provider
        and decision.model == legacy_model
    )
    if os.environ.get("HERMES_MODEL_ROUTER_SHADOW", "").strip().lower() in _TRUTHY:
        emit(
            "model.route.shadow_compare",
            status="ok",
            extra={
                "profile": profile,
                "legacyProvider": legacy_provider,
                "legacyModel": legacy_model,
                "provider": decision.provider,
                "model": decision.model,
                "same": same,
                "reasonCode": decision.reasonCode,
            },
        )
    return decision