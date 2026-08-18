"""Sandbox feature flags (Sprint 1.3.5 §32/§42) — strict parser, fail-closed, kill switch."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

FLAG_ENABLED = "HERMES_SANDBOX_MUTATION_V2_ENABLED"
FLAG_MODE = "HERMES_SANDBOX_MUTATION_V2_MODE"

VALID_MODES = ("off", "shadow", "sandbox")


def parse_flag(value: Optional[str]) -> bool:
    """Strict boolean parser: true/false/1/0/yes/no, case-insensitive.

    Missing or garbage → False (fail closed).
    """
    if value is None:
        return False
    v = value.strip().lower()
    if v in ("true", "1", "yes", "on"):
        return True
    if v in ("false", "0", "no", "off", ""):
        return False
    return False


def parse_mode(value: Optional[str]) -> str:
    if value is None:
        return "off"
    v = value.strip().lower()
    return v if v in VALID_MODES else "off"


@dataclass(frozen=True)
class SandboxFlags:
    enabled: bool = False
    mode: str = "off"

    @property
    def mutation_allowed(self) -> bool:
        """Kill switch: only ENABLED=true AND mode=sandbox allows mutation."""
        return self.enabled and self.mode == "sandbox"

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "mode": self.mode}


def flags_from_env(env=None) -> SandboxFlags:
    env = env if env is not None else os.environ
    return SandboxFlags(
        enabled=parse_flag(env.get(FLAG_ENABLED)),
        mode=parse_mode(env.get(FLAG_MODE)),
    )
