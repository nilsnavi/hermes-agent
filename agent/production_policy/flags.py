"""Sprint 1.3.8 §21 — narrowly scoped limited-production-mutation feature flags."""
from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum

ENABLED = "HERMES_LIMITED_PROD_MUTATION_V2_ENABLED"   # false default
MODE = "HERMES_LIMITED_PROD_MUTATION_V2_MODE"          # off/shadow/limited; unknown->off
PER_PROFILE = {
    "marker": "HERMES_PROD_PROFILE_MARKER",
    "json": "HERMES_PROD_PROFILE_JSON",
    "text": "HERMES_PROD_PROFILE_TEXT",
}


class Mode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    LIMITED = "limited"


def _val(name: str, env: Mapping[str, str] | None) -> str | None:
    e = os.environ if env is None else env
    return e.get(name)


def get_mode(env: Mapping[str, str] | None = None) -> Mode:
    raw = (_val(MODE, env) or "off").strip().lower()
    try:
        return Mode(raw)
    except ValueError:
        return Mode.OFF  # UNKNOWN -> off


def get_enabled(env: Mapping[str, str] | None = None) -> bool:
    return (_val(ENABLED, env) or "false").strip().lower() in ("1", "true", "yes")


def profile_enabled(name: str, env: Mapping[str, str] | None = None) -> bool:
    key = PER_PROFILE.get(name)
    if not key:
        return False
    return (_val(key, env) or "false").strip().lower() in ("1", "true", "yes")


def limited_active(env: Mapping[str, str] | None = None) -> bool:
    """Mutation-capable ONLY in limited mode AND enabled."""
    return get_mode(env) is Mode.LIMITED and get_enabled(env)
