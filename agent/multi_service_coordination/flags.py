"""Sprint 1.3.15 — multi-service coordination feature flags.

HERMES_MULTI_SERVICE_COORD_V2_ENABLED
HERMES_MULTI_SERVICE_COORD_V2_MODE

Modes: off | shadow | rehearsal.
NO live / canary mode exists in Sprint 1.3.15.  Any unknown or absent mode
resolves to the safest value: ``off``.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

ENABLED = "HERMES_MULTI_SERVICE_COORD_V2_ENABLED"
MODE = "HERMES_MULTI_SERVICE_COORD_V2_MODE"

ALLOWED_MODES = ("off", "shadow", "rehearsal")

_TRUE = {"1", "true", "yes"}


def _parse_flag(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in _TRUE


def multi_coord_enabled(env: Mapping[str, str] | None = None) -> bool:
    env = env if env is not None else os.environ
    return _parse_flag(env.get(ENABLED))


def multi_coord_mode(env: Mapping[str, str] | None = None) -> str:
    env = env if env is not None else os.environ
    mode = env.get(MODE, "off")
    return mode if mode in ALLOWED_MODES else "off"


def live_execution_permitted(superficial: Mapping[str, str] | None = None) -> bool:
    """Always False in Sprint 1.3.15 regardless of flags.

    This is the single place that would flip if a future sprint ever adds a
    live mode; until then it is hard-wired closed.
    """
    return False


__all__ = [
    "ALLOWED_MODES",
    "ENABLED",
    "MODE",
    "live_execution_permitted",
    "multi_coord_enabled",
    "multi_coord_mode",
]