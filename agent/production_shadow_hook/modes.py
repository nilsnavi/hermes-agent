"""Phase 8 hook modes + feature flags + kill switch (§1, §25, §26).

Modes: OFF (default) / TEST / CANARY. Activation is only via an EXPLICIT operator
gate; the code default is OFF. The feature flag
``HERMES_AGENT_PLATFORM_SHADOW_HOOK_ENABLED`` defaults to False and an UNKNOWN
value resolves to False. The kill switch ``HERMES_AGENT_PLATFORM_SHADOW_HOOK_KILL_SWITCH``
defaults to ON (shadow disabled): when killed, the hook returns immediately and
enqueues 0, leaving production unaffected.
"""

from __future__ import annotations

import os
from enum import Enum


class HookMode(Enum):
    OFF = "off"
    TEST = "test"
    CANARY = "canary"


ENABLED_ENV = "HERMES_AGENT_PLATFORM_SHADOW_HOOK_ENABLED"
KILL_SWITCH_ENV = "HERMES_AGENT_PLATFORM_SHADOW_HOOK_KILL_SWITCH"


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in ("1", "true", "yes", "on")


def default_hook_enabled() -> bool:
    """Feature flag: default False; UNKNOWN (missing) resolves to False."""
    return _truthy(os.getenv(ENABLED_ENV, ""))


def default_kill_switch() -> bool:
    """Kill switch: default ON (shadow disabled); OFF only if explicitly '0'/'false'."""
    env = os.getenv(KILL_SWITCH_ENV, "")
    return not (env.strip().lower() in ("0", "false", "off", "no"))


class HookConfiguration:
    """Immutable resolved config (flags captured at construction)."""

    __slots__ = ("enabled", "kill_switch", "mode", "sample_rate_per_mille")

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        kill_switch: bool | None = None,
        mode: HookMode = HookMode.OFF,
        sample_rate_per_mille: int = 0,
    ) -> None:
        self.enabled = default_hook_enabled() if enabled is None else bool(enabled)
        self.kill_switch = default_kill_switch() if kill_switch is None else bool(kill_switch)
        if type(mode) is not HookMode:
            raise ValueError("mode must be an exact HookMode value")
        if not isinstance(sample_rate_per_mille, int) or not (0 <= sample_rate_per_mille <= 1000):
            raise ValueError("sample_rate_per_mille must be in [0, 1000]")
        self.mode = mode
        self.sample_rate_per_mille = sample_rate_per_mille

    def active(self) -> bool:
        """Hook may tap traffic ONLY if enabled AND not kill-switched AND mode != OFF."""
        return self.enabled and not self.kill_switch and self.mode is not HookMode.OFF

    def sample_per_mille(self) -> int:
        # Controlled canary: bounded by config; 0 in OFF/TEST means no live tap.
        if self.mode is HookMode.OFF:
            return 0
        return self.sample_rate_per_mille


__all__ = [
    "ENABLED_ENV",
    "HookConfiguration",
    "HookMode",
    "KILL_SWITCH_ENV",
    "default_hook_enabled",
    "default_kill_switch",
]