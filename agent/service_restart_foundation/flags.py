"""Sprint 1.3.12 — service restart foundation flags.

Modes: off | shadow | inspect. NOT canary/execute/enforce.
Unknown mode/toggle -> safest default (off).
"""
from __future__ import annotations

import os
from collections.abc import Mapping

ENABLED = "HERMES_SERVICE_RESTART_FOUNDATION_V2_ENABLED"
MODE = "HERMES_SERVICE_RESTART_FOUNDATION_V2_MODE"

_VALID_MODES = {"off", "shadow", "inspect"}


def mode(env: Mapping[str, str] | None = None) -> str:
    env = env if env is not None else os.environ
    m = env.get(MODE, "off")
    return m if m in _VALID_MODES else "off"


def enabled(env: Mapping[str, str] | None = None) -> bool:
    env = env if env is not None else os.environ
    return env.get(ENABLED, "false").lower() in ("1", "true", "yes")


def foundation_disabled(env: Mapping[str, str] | None = None) -> bool:
    """True when the foundation must not even model mutation (1.3.12 default)."""
    return not enabled(env)


def restart_authority(env: Mapping[str, str] | None = None) -> bool:
    """Restart execution authority: ALWAYS False in 1.3.12 regardless of flags."""
    return False