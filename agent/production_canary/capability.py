"""Sprint 1.3.7 §6/§11/§24 — capability + policy gate for the single canary capability.

Risk: LOW_MUTATION (NOT read-only). Allowed ONLY when every exact-identity and
safety condition holds. No glob targets, no prefix-only checks, no broad
capabilities (SYSTEM_CONTROL / SYSTEM_WRITE / FILE_WRITE_ANY always denied).
"""
from __future__ import annotations

from dataclasses import dataclass

from .core import (CANARY_BOUNDARY_DENY_CLASSES, CANARY_CAPABILITY,
                   CANARY_OPERATION)
from .flags import canary_enabled, get_mode, Mode


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def risk_class(capability: str) -> str:
    if capability == CANARY_CAPABILITY:
        return "LOW_MUTATION"
    return "DENY"


def decide(capability: str, *, target: str, operation: str,
           target_allowed: bool, approval_valid: bool, baseline_ok: bool,
           health_ok: bool, mode: Mode | None = None,
           enabled: bool | None = None) -> PolicyDecision:
    """Narrow policy gate. All conditions must hold; any miss -> deny."""
    # capability must be exactly the narrow canary one
    if capability != CANARY_CAPABILITY:
        return PolicyDecision(False, "capability not allowed")
    # exact operation
    if operation != CANARY_OPERATION:
        return PolicyDecision(False, "operation not allowed")
    # exact target (allowlist resolved)
    if not target_allowed:
        return PolicyDecision(False, "target not in exact allowlist")
    # explicit approval
    if not approval_valid:
        return PolicyDecision(False, "explicit approval invalid/missing")
    # baseline correctness
    if not baseline_ok:
        return PolicyDecision(False, "baseline mismatch")
    # health gate
    if not health_ok:
        return PolicyDecision(False, "health not green")
    # canary gate = flag + mode canary
    if mode and mode is not Mode.CANARY:
        return PolicyDecision(False, "canary mode not active")
    if enabled is False:
        return PolicyDecision(False, "canary flag not enabled")
    return PolicyDecision(True, "ok")


def boundary_deny_class(operation: str) -> bool:
    """System-control families must stay DENY even with canary enabled."""
    return operation in CANARY_BOUNDARY_DENY_CLASSES
