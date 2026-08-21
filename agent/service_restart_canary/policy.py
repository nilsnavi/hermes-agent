"""Sprint 1.3.13 — single aux service restart canary (policy / admission).

Restart authority is a NARROW typed capability, separate from reload authority.
Only exact registered HERMES_AUXILIARY service. Implicit inheritance from reload
is forbidden: admission depends on a full restart contract, never on reload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Mapping

from ..service_restart_foundation.registry import class_allowed
from .allowlist import RestartAllowlist


class AdmissionVerdict(Enum):
    ADMITTED = "ADMITTED"
    DENY = "DENY"


@dataclass(frozen=True)
class AdmissionReason:
    verdict: AdmissionVerdict
    reason: str = ""


# Denied service classes inclusive of all non-aux and self-control classes.
_NON_CANARY = {
    "HERMES_CORE", "GATEWAY", "SCHEDULER", "PROVIDER", "DATABASE",
    "DATASTORE", "NETWORK", "SECURITY", "SSH", "DOCKER",
    "CONTAINER_RUNTIME", "AUTH", "UNKNOWN",
}


def _truthy(v) -> bool:
    if v is None:
        return False
    if isinstance(v, (list, tuple, set, dict, str)):
        return len(v) > 0
    return bool(v)


def _ctx(ctx: Mapping, key: str, default=None):
    if isinstance(ctx, Mapping):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def admission(
    service_id: str,
    unit_name: str,
    allowlist: RestartAllowlist,
    profile: Mapping | None = None,
    ctx: Mapping | None = None,
) -> AdmissionReason:
    """Fail-closed admission. Only the exact single canary passes."""
    # 1. exact allowlist (service + unit)
    if not allowlist.contains_service(service_id) or not allowlist.contains_unit(unit_name):
        return AdmissionReason(AdmissionVerdict.DENY, "not_registered")

    profile = profile or {}
    # 2. service_class == HERMES_AUXILIARY
    cls = profile.get("service_class", "UNKNOWN")
    if not class_allowed(cls):
        return AdmissionReason(AdmissionVerdict.DENY, "service_class_not_aux")
    if cls in _NON_CANARY:
        return AdmissionReason(AdmissionVerdict.DENY, "service_class_denied")

    # 3. criticality LOW
    if profile.get("criticality", "UNKNOWN") != "LOW":
        return AdmissionReason(AdmissionVerdict.DENY, "criticality_not_low")

    # 4. restart_supported
    if not profile.get("restart_supported", False):
        return AdmissionReason(AdmissionVerdict.DENY, "restart_not_supported")

    ctx = ctx or {}
    # 5. identity VERIFIED
    if not _ctx(ctx, "identity_verified", True):
        return AdmissionReason(AdmissionVerdict.DENY, "identity_unverified")

    # 6. graph HEALTHY
    if _ctx(ctx, "graph_status", "HEALTHY") != "HEALTHY":
        return AdmissionReason(AdmissionVerdict.DENY, "graph_stale")

    # 7. blast <= SERVICE
    if _ctx(ctx, "blast_radius", "SERVICE") != "SERVICE":
        return AdmissionReason(AdmissionVerdict.DENY, "blast_multiservice")

    # 8. dependents == 0
    if _truthy(_ctx(ctx, "dependents", ())):
        return AdmissionReason(AdmissionVerdict.DENY, "dependents_present")

    # 9. consumer NONE
    if _ctx(ctx, "consumer", "NONE") not in ("NONE", "NO_RUNTIME_CONSUMER", "PASSIVE_NONCRITICAL"):
        return AdmissionReason(AdmissionVerdict.DENY, "consumer_active")

    # 10. quiescence / startup / health / rollback contracts proven
    for ck, err in (("quiescence_proven", "quiescence_unproven"),
                    ("startup_proven", "startup_unproven"),
                    ("health_complete", "health_incomplete"),
                    ("rollback_proven", "rollback_unproven")):
        if not _ctx(ctx, ck, False):
            return AdmissionReason(AdmissionVerdict.DENY, err)

    # 11. pre-health RUNNING HEALTHY (runtime evidence, not just contract)
    if not _ctx(ctx, "pre_health_ok", True):
        return AdmissionReason(AdmissionVerdict.DENY, "prehealth_bad")
    # 12. executable / user identity verified
    if not _ctx(ctx, "executable_verified", True):
        return AdmissionReason(AdmissionVerdict.DENY, "executable_mismatch")
    if not _ctx(ctx, "user_verified", True):
        return AdmissionReason(AdmissionVerdict.DENY, "user_mismatch")

    return AdmissionReason(AdmissionVerdict.ADMITTED)


def negative_matrix_denied(service_id: str, unit_name: str,
                           allowlist: RestartAllowlist,
                           profile: Mapping | None = None,
                           ctx: Mapping | None = None) -> bool:
    """True when the service+context must be denied (negative matrix)."""
    return admission(service_id, unit_name, allowlist, profile, ctx).verdict == AdmissionVerdict.DENY


__all__ = [
    "AdmissionReason",
    "AdmissionVerdict",
    "admission",
    "negative_matrix_denied",
]