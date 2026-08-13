"""Gateway V2 feature flags (Sprint 1.0.6) — fail-closed by default.

Every flag defaults to FALSE; a missing or UNPARSEABLE value is FALSE.
Strict parser: true/false/1/0/yes/no (case-insensitive). There is no
truthy magic — ``"0"`` is False, ``"banana"`` is False, absent is False.

Modes (see matrix in docs/hermes-v2/production-activation.md):
    all false           → LEGACY only
    SHADOW=true         → legacy executes + non-executing V2 observation
    CANARY=true         → V2 executes ONLY explicit eligible read-only flow
    global replacement  → NOT IMPLEMENTED
"""

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

ENABLED = "HERMES_RUNTIME_V2_ENABLED"
PERSISTENCE = "HERMES_RUNTIME_V2_PERSISTENCE"
ORCHESTRATOR = "HERMES_RUNTIME_V2_ORCHESTRATOR"
SHADOW = "HERMES_RUNTIME_V2_SHADOW"
CANARY = "HERMES_RUNTIME_V2_CANARY"

FLAG_NAMES = (ENABLED, PERSISTENCE, ORCHESTRATOR, SHADOW, CANARY)

_TRUTHY = {"true": True, "1": True, "yes": True}
_FALSY = {"false": False, "0": False, "no": False}


def parse_flag(value: Optional[str]) -> bool:
    """Strict boolean parse. None/invalid → False (fail closed)."""
    if value is None:
        return False
    normalized = str(value).strip().lower()
    if normalized in _TRUTHY:
        return True
    return False  # "0", "no", garbage, everything else → False


def read_flags(environ: Optional[Mapping[str, str]] = None) -> "FeatureFlags":
    """Current flags from the environment (defaults: all false)."""
    return FeatureFlags.from_env(environ)


@dataclass(frozen=True)
class FeatureFlags:
    enabled: bool = False
    persistence: bool = False
    orchestrator: bool = False
    shadow: bool = False
    canary: bool = False

    @classmethod
    def from_mapping(cls, values: Mapping[str, Optional[str]]) -> "FeatureFlags":
        return cls(
            enabled=parse_flag(values.get(ENABLED)),
            persistence=parse_flag(values.get(PERSISTENCE)),
            orchestrator=parse_flag(values.get(ORCHESTRATOR)),
            shadow=parse_flag(values.get(SHADOW)),
            canary=parse_flag(values.get(CANARY)),
        )

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "FeatureFlags":
        import os

        return cls.from_mapping(environ if environ is not None else os.environ)

    def to_dict(self) -> Dict[str, bool]:
        return {
            "enabled": self.enabled,
            "persistence": self.persistence,
            "orchestrator": self.orchestrator,
            "shadow": self.shadow,
            "canary": self.canary,
        }

    def mode(self) -> str:
        """Effective mode: ``legacy`` | ``shadow`` | ``canary``.

        ENABLED is the master gate — without it nothing V2 activates.
        """
        if not self.enabled:
            return "legacy"
        if self.canary:
            return "canary"
        if self.shadow:
            return "shadow"
        return "legacy"
