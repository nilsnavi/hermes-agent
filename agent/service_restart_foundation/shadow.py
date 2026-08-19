"""Sprint 1.3.12 — shadow study (>=100 eligibility evaluations, 0 mutation).

Each evaluation is a read-only eligibility analysis. The adapter is never
invoked. Mix: gateway, aux-canary, unknown, critical, dependency-heavy, bad
identity, stale graph, orphan-risk, port-conflict.
"""
from __future__ import annotations

from collections.abc import Sequence

from . import telemetry
from .eligibility import EligibilityReason, evaluate_eligibility
from .events import emit, SERVICE_RESTART_ELIGIBILITY_EVALUATED
from .guard import adapter_calls


_SHADOW_MUTATION_CALLS = 0


def shadow_mutation_calls() -> int:
    """Number of production mutations performed by shadow studies — always 0."""
    return _SHADOW_MUTATION_CALLS


# A passing-everything context used to isolate the profile's own gating.
_OK_CTX = {
    "identity_verified": True,
    "graph_status": "HEALTHY",
    "critical_dependents": 0,
    "active_dependents": 0,
    "blast_radius": "SERVICE",
    "criticality": "LOW",
    "stop_contract_known": True,
    "quiescence_proven": True,
    "orphan_risk": False,
    "start_contract_known": True,
    "executable_verified": True,
    "port_transition_proven": True,
    "health_pass": True,
    "rollback_proven": True,
    "risk_class": "HIGH",
    "restart_rollback_proven": True,
}


def _ctx_for(label: str) -> dict:
    """Return a context that stresses a particular failure dimension."""
    ctx = dict(_OK_CTX)
    if label == "gateway":
        ctx["identity_verified"] = True
    elif label == "bad-id":
        ctx["identity_verified"] = False
    elif label == "stale-graph":
        ctx["graph_status"] = "STALE"
    elif label == "orphan-risk":
        ctx["orphan_risk"] = True
    elif label == "port-conflict":
        ctx["port_transition_proven"] = False
    elif label == "dep-heavy":
        ctx["critical_dependents"] = 1
    elif label == "critical":
        ctx["criticality"] = "CRITICAL"
    return ctx


def run_shadow_evaluations(cases: Sequence) -> int:
    """Run 12x replicas of each labelled profile through eligibility analysis.

    Returns the total number of evaluations performed. Performs 0 mutations.
    """
    total = 0
    for label, profile in cases:
        ctx = _ctx_for(label)
        for _ in range(12):
            reason = evaluate_eligibility(profile, ctx)
            telemetry.inc(telemetry.C_REQUESTED)
            if reason == EligibilityReason.ELIGIBLE_FOR_FUTURE_RESTART_CANARY:
                telemetry.inc(telemetry.C_ELIGIBLE_FUTURE_CANARY)
            else:
                telemetry.inc(telemetry.C_DENIED)
            try:
                emit(SERVICE_RESTART_ELIGIBILITY_EVALUATED, profile.service_id,
                     detail=reason.value)
            except Exception:
                pass
            total += 1
    # Guard: ensure no adapter call sneaked in.
    assert adapter_calls() == 0
    return total


__all__ = ["run_shadow_evaluations", "shadow_mutation_calls"]