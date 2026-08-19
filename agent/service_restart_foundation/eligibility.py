"""Sprint 1.3.12 — restart eligibility (strict fail-closed precedence).

ELIGIBLE_FOR_FUTURE_RESTART_CANARY is NOT execution authority; the execution
guard (guard.py) always blocks in 1.3.12.

Precedence:
  1 self-control
  2 service class
  3 identity (identity + executable)
  4 dependency graph health
  5 criticality (CRITICAL denied for 1.3.12)
  6 dependency-phase blast
  7 blast radius ceiling
  8 stop contract
  9 quiescence
  10 orphan proof
  11 start contract
  12 port transition
  13 health contract
  14 rollback/recovery proof
  15 risk monotonicity
"""
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from .blast_radius import blast_acceptable, compute_blast_radius
from .registry import class_allowed, HARD_DENY_CLASSES
from .risk import restart_risk_acceptable


class EligibilityReason(Enum):
    ELIGIBLE_FOR_FUTURE_RESTART_CANARY = "ELIGIBLE_FOR_FUTURE_RESTART_CANARY"
    SELF_CONTROL_FORBIDDEN = "SELF_CONTROL_FORBIDDEN"
    SERVICE_CLASS_DENIED = "SERVICE_CLASS_DENIED"
    IDENTITY_UNVERIFIED = "IDENTITY_UNVERIFIED"
    GRAPH_UNHEALTHY = "GRAPH_UNHEALTHY"
    BLAST_TOO_HIGH = "BLAST_TOO_HIGH"
    DEPENDENCY_RISK = "DEPENDENCY_RISK"
    STOP_CONTRACT_MISSING = "STOP_CONTRACT_MISSING"
    START_CONTRACT_MISSING = "START_CONTRACT_MISSING"
    QUIESCENCE_UNPROVEN = "QUIESCENCE_UNPROVEN"
    PORT_TRANSITION_UNPROVEN = "PORT_TRANSITION_UNPROVEN"
    HEALTH_CONTRACT_MISSING = "HEALTH_CONTRACT_MISSING"
    ROLLBACK_UNPROVEN = "ROLLBACK_UNPROVEN"
    ORPHAN_RISK = "ORPHAN_RISK"
    CRITICALITY_DENIED = "CRITICALITY_DENIED"
    RISK_TOO_LOW = "RISK_TOO_LOW"
    UNKNOWN = "UNKNOWN"


# Classes that represent Hermes controlling its own runtime: self-control is
# ALWAYS forbidden, even with a verified identity.
_SELF_CONTROL_CLASSES = {
    "HERMES_CORE",
    "GATEWAY",
    "SCHEDULER",
    "PROVIDER",
    "RUNTIME",
    "AGENT_CORE",
}


def _is_self_control(profile) -> bool:
    if profile.service_id in ("hermes-gateway", "hermes", "agent", "runtime"):
        return True
    return profile.service_class in _SELF_CONTROL_CLASSES


def _ctx_get(ctx: Mapping, key: str, default=None):
    if isinstance(ctx, Mapping):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def _seq_truthy(v) -> bool:
    if v is None:
        return False
    if isinstance(v, (list, tuple, set, dict, str)):
        return len(v) > 0
    return bool(v)


def evaluate_eligibility(profile, ctx) -> EligibilityReason:
    """Strict fail-closed eligibility evaluation. Returns an EligibilityReason."""
    try:
        # 1. self-control — always forbidden
        if _is_self_control(profile):
            return EligibilityReason.SELF_CONTROL_FORBIDDEN

        # 2. service class — only HERMES_AUXILIARY
        if not class_allowed(profile.service_class):
            return EligibilityReason.SERVICE_CLASS_DENIED

        identity_verified = _ctx_get(ctx, "identity_verified", True)
        executable_verified = _ctx_get(ctx, "executable_verified", True)
        # 3. identity (identity + expected executable identity)
        if not identity_verified or not executable_verified:
            return EligibilityReason.IDENTITY_UNVERIFIED

        # 4. dependency graph health
        graph_status = _ctx_get(ctx, "graph_status", "HEALTHY")
        if graph_status != "HEALTHY":
            return EligibilityReason.GRAPH_UNHEALTHY

        # 5. criticality — CRITICAL auxiliary services are denied in 1.3.12
        criticality = profile.criticality or _ctx_get(ctx, "criticality", "LOW")
        if criticality == "CRITICAL":
            return EligibilityReason.CRITICALITY_DENIED

        # 6. dependency risk (named/active dependents)
        crit_deps = _ctx_get(ctx, "critical_dependents", ())
        act_deps = _ctx_get(ctx, "active_dependents", ())
        if _seq_truthy(crit_deps) or _seq_truthy(act_deps):
            return EligibilityReason.DEPENDENCY_RISK

        # 7. blast radius ceiling
        blast = _ctx_get(ctx, "blast_radius",
                         compute_blast_radius(
                             profile.blast_radius_ceiling,
                             critical_dependents=crit_deps or (),
                             active_dependents=act_deps or (),
                         ))
        if not blast_acceptable(blast):
            return EligibilityReason.BLAST_TOO_HIGH

        # 8. stop contract
        if not _ctx_get(ctx, "stop_contract_known", True):
            return EligibilityReason.STOP_CONTRACT_MISSING

        # 9. quiescence
        if not _ctx_get(ctx, "quiescence_proven", True):
            return EligibilityReason.QUIESCENCE_UNPROVEN

        # 10. orphan proof
        if _ctx_get(ctx, "orphan_risk", False):
            return EligibilityReason.ORPHAN_RISK

        # 11. start contract
        if not _ctx_get(ctx, "start_contract_known", True):
            return EligibilityReason.START_CONTRACT_MISSING

        # 12. port transition
        if not _ctx_get(ctx, "port_transition_proven", True):
            return EligibilityReason.PORT_TRANSITION_UNPROVEN

        # 13. health contract
        if not _ctx_get(ctx, "health_pass", True):
            return EligibilityReason.HEALTH_CONTRACT_MISSING

        # 14. rollback / recovery proof
        rollback_proven = _ctx_get(ctx, "rollback_proven", True)
        restart_rollback_proven = _ctx_get(ctx, "restart_rollback_proven", True)
        if not rollback_proven or not restart_rollback_proven:
            return EligibilityReason.ROLLBACK_UNPROVEN

        # 15. risk monotonicity — restart risk must not be below reload baseline
        prof_risk = getattr(profile, "risk_class", "HIGH")
        if not restart_risk_acceptable(prof_risk):
            return EligibilityReason.RISK_TOO_LOW

        # All gates pass -> future-canary eligibility (NOT authority).
        return EligibilityReason.ELIGIBLE_FOR_FUTURE_RESTART_CANARY
    except Exception:  # fail closed
        return EligibilityReason.UNKNOWN


def eligibility_actionable(reason: EligibilityReason) -> bool:
    """Only future-canary eligibility is actionable, and even that does NOT
    grant execution authority (guard is separate)."""
    return reason == EligibilityReason.ELIGIBLE_FOR_FUTURE_RESTART_CANARY


__all__ = ["EligibilityReason", "eligibility_actionable", "evaluate_eligibility"]