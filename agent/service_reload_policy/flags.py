"""Sprint 1.3.11 — flags (off/shadow/limited)."""
from __future__ import annotations

import os
from collections.abc import Mapping

ENABLED = "HERMES_LIMITED_SERVICE_RELOAD_V2_ENABLED"
MODE = "HERMES_LIMITED_SERVICE_RELOAD_V2_MODE"

_VALID = {"off", "shadow", "limited"}


def mode(env: Mapping[str, str] | None = None) -> str:
    env = env or os.environ
    m = env.get(MODE, "off")
    return m if m in _VALID else "off"


def enabled(env: Mapping[str, str] | None = None) -> bool:
    env = env or os.environ
    return env.get(ENABLED, "false").lower() in ("1", "true", "yes")