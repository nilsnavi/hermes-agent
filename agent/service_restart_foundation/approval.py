"""Sprint 1.3.12 — approval foundation (shadow-only).

Future restart approval must bind to: service, profile version, old identity,
graph, stop/start contracts, health, rollback, risk, blast, plan hash, TTL.
In 1.3.12 approval evaluation is shadow-only — no production approval ever.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .guard import restart_execution_guard


class ApprovalVerdict(Enum):
    APPROVED_SHADOW = "APPROVED_SHADOW"
    PENDING = "PENDING"
    DENIED = "DENIED"


@dataclass(frozen=True)
class RestartApproval:
    service_id: str
    plan_hash: str
    profile_version: int
    old_identity: str
    graph_digest: str
    risk: str
    blast_radius: str
    evaluated_at: float = 0.0
    ttl: float = 300.0
    verdict: ApprovalVerdict = ApprovalVerdict.PENDING
    bound_fields: tuple = field(default_factory=tuple)


def evaluate_approval(
    service_id: str,
    plan_hash: str,
    profile_version: int,
    old_identity: str,
    graph_digest: str,
    risk: str,
    blast_radius: str,
    health_ok: bool,
    rollback_ok: bool,
) -> RestartApproval:
    """Shadow-only approval evaluation. Never results in production approval."""
    fields = (
        service_id, plan_hash, str(profile_version), old_identity,
        graph_digest, risk, blast_radius, str(health_ok), str(rollback_ok),
    )
    verdict = ApprovalVerdict.PENDING
    if health_ok and rollback_ok and blast_radius == "SERVICE":
        verdict = ApprovalVerdict.APPROVED_SHADOW
    else:
        verdict = ApprovalVerdict.DENIED
    return RestartApproval(
        service_id=service_id,
        plan_hash=plan_hash,
        profile_version=profile_version,
        old_identity=old_identity,
        graph_digest=graph_digest,
        risk=risk,
        blast_radius=blast_radius,
        verdict=verdict,
        bound_fields=tuple(fields),
    )


def approval_grants_execution(_: RestartApproval) -> str:
    """An approval NEVER grants execution in 1.3.12 — the guard always blocks."""
    return restart_execution_guard()


__all__ = [
    "ApprovalVerdict",
    "RestartApproval",
    "approval_grants_execution",
    "evaluate_approval",
]