"""Sprint 1.3.9 — service foundation feature flags (shadow/inspect only)."""
from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum


class ServiceMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    INSPECT = "inspect"


_ENABLED = "HERMES_SERVICE_FOUNDATION_V2_ENABLED"


def foundation_enabled(env: Mapping[str, str] | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(_ENABLED, "false")).strip().lower() in ("1", "true", "yes")


def get_mode(env: Mapping[str, str] | None = None) -> ServiceMode:
    e = env if env is not None else os.environ
    raw = str(e.get("HERMES_SERVICE_FOUNDATION_V2_MODE", "off")).strip().lower()
    for m in ServiceMode:
        if m.value == raw:
            return m
    return ServiceMode.OFF  # unknown -> off
