"""Sprint 1.3.17 — feature flags for bounded multi-service execution.

HERMES_MULTI_SERVICE_EXECUTION_V2_ENABLED
HERMES_MULTI_SERVICE_EXECUTION_V2_MODE

Modes: off | shadow | rehearsal | canary.
Unknown or absent mode resolves to the SAFEST value: ``off``.

P0: even if ENABLED=true, real production adapter calls MUST remain 0.
``live_execution_permitted`` is hard-wired closed for this sprint: there is no
production adapter path to unlock.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

ENABLED = "HERMES_MULTI_SERVICE_EXECUTION_V2_ENABLED"
MODE = "HERMES_MULTI_SERVICE_EXECUTION_V2_MODE"

ALLOWED_MODES = ("off", "shadow", "rehearsal", "canary")

_TRUE = {"1", "true", "yes"}


def _parse_flag(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in _TRUE


def multi_exec_enabled(env: Mapping[str, str] | None = None) -> bool:
    env = env if env is not None else os.environ
    return _parse_flag(env.get(ENABLED))


def multi_exec_mode(env: Mapping[str, str] | None = None) -> str:
    env = env if env is not None else os.environ
    mode = env.get(MODE, "off")
    return mode if mode in ALLOWED_MODES else "off"


def live_execution_permitted(env: Mapping[str, str] | None = None) -> bool:
    """Hard-wired closed in Sprint 1.3.17 regardless of flags.

    There is no production adapter in this package; the only way to become
    ``True`` is a future sprint that introduces a real execution path.
    """
    return False


__all__ = [
    "ALLOWED_MODES",
    "ENABLED",
    "MODE",
    "live_execution_permitted",
    "multi_exec_enabled",
    "multi_exec_mode",
]