"""Sprint 1.3.9 — health contract evaluation + config validation (read-only, bounded)."""
from __future__ import annotations

import json

from .models import HealthContract, HealthStatus, ValidatorResult


def evaluate_health(contract: HealthContract | None, checks: dict) -> HealthStatus:
    """Evaluate a read-only health contract from observed check results."""
    if contract is None:
        return HealthStatus.UNKNOWN
    results = [checks.get(c, HealthStatus.UNKNOWN) for c in contract.checks]
    if any(r is HealthStatus.UNHEALTHY for r in results):
        return HealthStatus.UNHEALTHY
    if any(r is HealthStatus.UNKNOWN for r in results):
        return HealthStatus.UNKNOWN
    if all(r is HealthStatus.HEALTHY for r in results):
        return HealthStatus.HEALTHY
    return HealthStatus.DEGRADED


def validate_config(validator, document) -> ValidatorResult:
    """Read-only bounded config validation. Never mutates. Unknown validator -> UNKNOWN."""
    if validator is None:
        return ValidatorResult.UNAVAILABLE
    if validator.kind == "json_schema":
        try:
            if isinstance(document, (bytes, bytearray)):
                json.loads(bytes(document))
            elif isinstance(document, str):
                json.loads(document)
            else:
                return ValidatorResult.UNKNOWN
            return ValidatorResult.VALID
        except (ValueError, TypeError):
            return ValidatorResult.INVALID
    return ValidatorResult.UNKNOWN
