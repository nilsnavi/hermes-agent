"""Validation registry (Sprint 1.3.3 §42-§43).

Static verified registry only: nginx -t, systemd-analyze verify, strict
JSON, safe YAML, docker compose config, sshd -t. An LLM, skill, plugin
or MCP description can NEVER register a trusted validator. If a
validator is missing for a mutation that requires validation →
VALIDATION_UNAVAILABLE → BLOCK/REVALIDATE.
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ValidationPlan:
    validator: str
    required: bool
    kind: str = "command"


class ValidatorRegistry:
    """Static, immutable validator table — no registration API."""

    _STATIC_VALIDATORS: Dict[str, str] = {
        "nginx config": "nginx -t",
        "systemd unit": "systemd-analyze verify",
        "json": "strict-parser",
        "yaml": "safe-parser",
        "docker compose": "docker compose config",
        "ssh config": "sshd -t",
        "caddyfile": "caddy validate",
        "traefik config": "traefik config check",
        "postgresql config": "postgres --check-config",
    }

    def validator_for(self, kind: str) -> Optional[str]:
        """Return the static validator for a config kind, or None."""
        return self._STATIC_VALIDATORS.get(str(kind).lower())

    def decision_for(self, kind: str, required: bool = True) -> str:
        """VALIDATION_UNAVAILABLE when a required validator is missing.

        Unknown kinds are NEVER satisfied — fail closed (§42).
        """
        if self.validator_for(kind) is not None:
            return "SBL_OK"
        if required:
            return "VALIDATION_UNAVAILABLE"
        return "SBL_OK"


def plan_validation(kind: str) -> ValidationPlan:
    """Validation planner — static table only."""
    validator = ValidatorRegistry().validator_for(kind)
    if validator is None:
        return ValidationPlan(validator="", required=True, kind=kind)
    return ValidationPlan(validator=validator, required=True, kind=kind)


__all__ = [
    "ValidatorRegistry",
    "ValidationPlan",
    "plan_validation",
]
