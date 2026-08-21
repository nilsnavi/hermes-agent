"""Sprint 1.3.13 — single aux service restart canary (flags).

Modes: off | shadow | canary. Unknown -> off. Flag NEVER grants authority.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

ENABLED = "HERMES_SERVICE_RESTART_CANARY_V2_ENABLED"
MODE = "HERMES_SERVICE_RESTART_CANARY_V2_MODE"

_VALID_MODES = {"off", "shadow", "canary"}


def mode(env: Mapping[str, str] | None = None) -> str:
    env = env if env is not None else os.environ
    m = env.get(MODE, "off")
    return m if m in _VALID_MODES else "off"


def enabled(env: Mapping[str, str] | None = None) -> bool:
    env = env if env is not None else os.environ
    return env.get(ENABLED, "false").lower() in ("1", "true", "yes")


def canary_active(env: Mapping[str, str] | None = None) -> bool:
    """Canary execution allowed only when ENABLED and MODE=canary."""
    return enabled(env) and mode(env) == "canary"


__all__ = ["ENABLED", "MODE", "canary_active", "enabled", "mode"]