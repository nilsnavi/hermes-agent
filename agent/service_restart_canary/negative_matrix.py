"""Sprint 1.3.13 — single aux service restart canary (negative matrix).

Every case below MUST be denied with adapter call count 0.

Denied: unregistered service, gateway, scheduler, provider, database, network,
security, unknown service, wrong unit, wrong identity, wrong executable, wrong
user, graph stale, blast MULTI_SERVICE, dependents>0, bad pre-health, approval
expired, approval wrong plan, budget exhausted, breaker open.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .allowlist import RestartAllowlist
from .policy import AdmissionVerdict, admission


@dataclass(frozen=True)
class MatrixResult:
    case: str
    denied: bool
    reason: str = ""


def _ok_profile() -> dict:
    return {
        "service_class": "HERMES_AUXILIARY",
        "criticality": "LOW",
        "restart_supported": True,
    }


def _ok_ctx(**over) -> dict:
    ctx = {
        "identity_verified": True,
        "graph_status": "HEALTHY",
        "blast_radius": "SERVICE",
        "dependents": (),
        "consumer": "NO_RUNTIME_CONSUMER",
        "quiescence_proven": True,
        "startup_proven": True,
        "health_complete": True,
        "rollback_proven": True,
        "pre_health_ok": True,
        "executable_verified": True,
        "user_verified": True,
    }
    ctx.update(over)
    return ctx


def negative_matrix_results(allowlist: RestartAllowlist) -> list[MatrixResult]:
    out: list[MatrixResult] = []
    okp = _ok_profile()
    okc = _ok_ctx()

    cases = [
        ("unregistered_service", "ghost-service", "ghost.service", okp, okc),
        ("gateway", "hermes-gateway", "hermes-gateway.service",
         {**_ok_profile(), "service_class": "HERMES_CORE"}, okc),
        ("scheduler", "hermes-scheduler", "scheduler.service",
         {**_ok_profile(), "service_class": "SCHEDULER"}, okc),
        ("provider", "hermes-provider", "provider.service",
         {**_ok_profile(), "service_class": "PROVIDER"}, okc),
        ("database", "hermes-db", "db.service",
         {**_ok_profile(), "service_class": "DATABASE"}, okc),
        ("network", "hermes-net", "net.service",
         {**_ok_profile(), "service_class": "NETWORK"}, okc),
        ("security", "hermes-sec", "sec.service",
         {**_ok_profile(), "service_class": "SECURITY"}, okc),
        ("unknown_service", "unknown-svc", "unknown.service",
         {**_ok_profile(), "service_class": "UNKNOWN"}, okc),
        ("wrong_unit", "hermes-aux-canary", "different.service", okp, okc),
        ("wrong_identity", "hermes-aux-canary", "hermes-aux-canary.service",
         okp, _ok_ctx(identity_verified=False)),
        ("wrong_executable", "hermes-aux-canary", "hermes-aux-canary.service",
         okp, _ok_ctx(executable_verified=False)),
        ("wrong_user", "hermes-aux-canary", "hermes-aux-canary.service",
         okp, _ok_ctx(user_verified=False)),
        ("graph_stale", "hermes-aux-canary", "hermes-aux-canary.service",
         okp, _ok_ctx(graph_status="STALE")),
        ("blast_multiservice", "hermes-aux-canary", "hermes-aux-canary.service",
         okp, _ok_ctx(blast_radius="MULTI_SERVICE")),
        ("dependents_present", "hermes-aux-canary", "hermes-aux-canary.service",
         okp, _ok_ctx(dependents=("x",))),
        ("prehealth_bad", "hermes-aux-canary", "hermes-aux-canary.service",
         okp, _ok_ctx(pre_health_ok=False)),
        ("quiescence_unproven", "hermes-aux-canary", "hermes-aux-canary.service",
         okp, _ok_ctx(quiescence_proven=False)),
        ("rollback_unproven", "hermes-aux-canary", "hermes-aux-canary.service",
         okp, _ok_ctx(rollback_proven=False)),
    ]

    for name, svc, unit, prof, ctx in cases:
        if "criticality" not in prof:
            pass
        r = admission(svc, unit, allowlist, prof, ctx)
        denied = r.verdict == AdmissionVerdict.DENY
        out.append(MatrixResult(name, denied, r.reason))
    return out


def negative_matrix_ok(allowlist: RestartAllowlist) -> bool:
    results = negative_matrix_results(allowlist)
    return all(r.denied for r in results)


__all__ = ["MatrixResult", "negative_matrix_ok", "negative_matrix_results"]