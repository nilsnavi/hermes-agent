"""Sprint 1.3.9 — service identity verification + class resolution."""
from __future__ import annotations

from .models import IdentityResult, ServiceClass, ServiceProfile


def classify(profile: ServiceProfile | None, fallback: ServiceClass = ServiceClass.UNKNOWN) -> ServiceClass:
    if profile is None:
        return fallback
    return profile.service_class


def verify_identity(profile: ServiceProfile | None, state: dict) -> IdentityResult:
    """Verify service identity from observed state (read-only).

    Identity is NOT unit name alone: unit/scope/manager + executable + ExecStart
    + ExecReload + user/group + PID/start + binary identity. Strong evidence
    required for VERIFIED; uncertainty lowers to PARTIAL/MISMATCH/UNKNOWN.
    """
    if profile is None:
        return IdentityResult.UNKNOWN
    unit = state.get("unit_name")
    if unit and unit != profile.unit_name:
        return IdentityResult.MISMATCH
    exe = state.get("executable")
    exp_exe = profile.expected_executable
    if exp_exe and exe:
        if exe.rstrip("/") != exp_exe.rstrip("/") and not exe.endswith(exp_exe):
            return IdentityResult.MISMATCH
        if exe:
            return IdentityResult.VERIFIED
    # weak / partial evidence
    if unit:
        return IdentityResult.PARTIAL
    if "MainPID" in state:
        return IdentityResult.PARTIAL
    return IdentityResult.UNKNOWN
