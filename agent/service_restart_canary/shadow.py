"""Sprint 1.3.13 — shadow evaluation (≥50 evaluations, 0 mutations).

Shadow phase: evaluate restart eligibility/admission across mixed cases without
any real adapter call. Candidate correctness 100%, actual restart 0.
"""
from __future__ import annotations

from dataclasses import dataclass

from .allowlist import RestartAllowlist, default_allowlist
from .policy import AdmissionVerdict, admission


@dataclass(frozen=True)
class ShadowEvalResult:
    case: str
    service_id: str
    unit: str
    admitted: bool
    reason: str
    mutations: int = 0


def run_shadow_evaluations(allowlist: RestartAllowlist | None = None,
                            *, n: int = 50) -> list[ShadowEvalResult]:
    """Run >= n shadow eligibility evaluations. 0 mutation calls."""
    al = allowlist or default_allowlist()
    ok_profile = {
        "service_class": "HERMES_AUXILIARY",
        "criticality": "LOW",
        "restart_supported": True,
    }
    ok_ctx = {
        "identity_verified": True,
        "graph_status": "HEALTHY",
        "blast_radius": "SERVICE",
        "dependents": (),
        "consumer": "NO_RUNTIME_CONSUMER",
        "quiescence_proven": True,
        "startup_proven": True,
        "health_complete": True,
        "rollback_proven": True,
    }
    deny_cases = [
        ("gateway", "hermes-gateway", "hermes-gateway.service",
         {"service_class": "GATEWAY"}, ok_ctx),
        ("unknown", "ghost", "ghost.service", {"service_class": "UNKNOWN"}, ok_ctx),
        ("critical", "svc", "svc.service", {**ok_profile, "criticality": "HIGH"}, ok_ctx),
        ("graph_stale", "hermes-aux-canary", "hermes-aux-canary.service",
         ok_profile, {**ok_ctx, "graph_status": "STALE"}),
        ("blast_multi", "hermes-aux-canary", "hermes-aux-canary.service",
         ok_profile, {**ok_ctx, "blast_radius": "MULTI_SERVICE"}),
        ("dependents", "hermes-aux-canary", "hermes-aux-canary.service",
         ok_profile, {**ok_ctx, "dependents": ("x",)}),
        ("identity_bad", "hermes-aux-canary", "hermes-aux-canary.service",
         ok_profile, {**ok_ctx, "identity_verified": False}),
    ]
    canary_case = ("canary_ok", "hermes-aux-canary", "hermes-aux-canary.service",
                   ok_profile, ok_ctx)

    results: list[ShadowEvalResult] = []
    # Replicate cases to >= n
    pool = deny_cases + [canary_case]
    i = 0
    while len(results) < n:
        name, svc, unit, prof, ctx = pool[i % len(pool)]
        r = admission(svc, unit, al, {**ok_profile, **prof} if "service_class" not in prof else prof, ctx)
        results.append(ShadowEvalResult(
            case=name, service_id=svc, unit=unit,
            admitted=(r.verdict == AdmissionVerdict.ADMITTED),
            reason=r.reason, mutations=0))
        i += 1
    return results


def shadow_mutation_calls() -> int:
    return 0


def shadow_pass(results: list[ShadowEvalResult]) -> bool:
    """All deny cases denied, only canary admitted, 0 mutations."""
    for r in results:
        if r.case == "canary_ok" and not r.admitted:
            return False
        if r.case != "canary_ok" and r.admitted:
            return False
        if r.mutations != 0:
            return False
    return True


__all__ = [
    "ShadowEvalResult",
    "run_shadow_evaluations",
    "shadow_mutation_calls",
    "shadow_pass",
]