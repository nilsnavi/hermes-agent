"""Sprint 1.3.7 §7/§9 — narrowly scoped production-canary feature flags.

Modes: off / shadow / canary. UNKNOWN -> off (fail closed).
``canary_enabled()`` requires BOTH flag=True AND mode=canary.
The env-supplied target is NEVER trusted by itself — it must match the
compiled exact allowlist (target_allowlist.resolve()).
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum


class Mode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    CANARY = "canary"


_ENABLED_ENV = "HERMES_PRODUCTION_CANARY_V2_ENABLED"
_MODE_ENV = "HERMES_PRODUCTION_CANARY_V2_MODE"


def get_flag_enabled(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    raw = env.get(_ENABLED_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def get_mode(env: Mapping[str, str] | None = None) -> Mode:
    env = os.environ if env is None else env
    raw = env.get(_MODE_ENV, "").strip().lower()
    for candidate in Mode:
        if raw == candidate.value:
            return candidate
    return Mode.OFF  # unknown -> off (fail closed)


def canary_enabled(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return get_flag_enabled(env) and get_mode(env) is Mode.CANARY


def get_target_env(env: Mapping[str, str] | None = None) -> str | None:
    """Env target hint. NOT trusted — must match compiled allowlist."""
    env = os.environ if env is None else env
    return env.get("HERMES_PRODUCTION_CANARY_TARGET") or None
