"""Sprint 1.3.12 — immutable ServiceRestartPlan + binding + revalidation.

Plan is bound to: profile version, identity, graph, ports, health, risk, blast,
stop/start contracts, baseline SHA, TTL. Drift -> REVALIDATE_REQUIRED.
"""
from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from .models import RestartProfile


class PlanRevalidation(Enum):
    VALID = "VALID"
    REVALIDATE_REQUIRED = "REVALIDATE_REQUIRED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ServiceRestartPlan:
    plan_id: str
    transaction_id: str
    service_id: str
    profile_version: int
    operation: str = "RESTART"
    identity_fingerprint: str = ""
    graph_digest: str = ""
    old_pid_identity: str = ""
    expected_stop_contract: str = ""
    quiescence_contract: str = ""
    expected_start_contract: str = ""
    health_contract: str = ""
    risk: str = "HIGH"
    blast_radius: str = "SERVICE"
    rollback_strategy: str = "RECONCILE_CURRENT_STATE"
    recovery_strategy: str = "RECONCILE_CURRENT_STATE"
    approval_required: bool = True
    created_at: float = 0.0
    expires_at: float = 0.0
    profile_version_bound: int = 1
    baseline_sha: str = ""
    ports: tuple = field(default_factory=tuple)


def build_restart_plan(profile: RestartProfile,
                       transaction_id: str,
                       *,
                       plan_id: str | None = None,
                       identity_fingerprint: str = "verified",
                       graph_digest: str = "graph-v1",
                       old_pid_identity: str = "old",
                       baseline_sha: str = "baseline1",
                       created_at: float | None = None,
                       ttl: float = 3600.0) -> ServiceRestartPlan:
    """Construct an immutable restart plan bound to the given profile."""
    now = created_at if created_at is not None else time.time()
    return ServiceRestartPlan(
        plan_id=plan_id or f"rp-{transaction_id}",
        transaction_id=transaction_id,
        service_id=profile.service_id,
        profile_version=profile.profile_version,
        operation="RESTART",
        identity_fingerprint=identity_fingerprint,
        graph_digest=graph_digest,
        old_pid_identity=old_pid_identity,
        expected_stop_contract=f"stop-{profile.startup_contract_id}",
        quiescence_contract=f"q-{profile.quiescence_policy}",
        expected_start_contract=f"start-{profile.startup_contract_id}",
        health_contract=f"health-{profile.health_contract_id}",
        risk=profile.risk_class,
        blast_radius=profile.blast_radius_ceiling,
        rollback_strategy=profile.rollback_strategy,
        recovery_strategy=profile.rollback_strategy,
        approval_required=True,
        created_at=now,
        expires_at=now + ttl,
        profile_version_bound=profile.profile_version,
        baseline_sha=baseline_sha,
        ports=tuple(profile.expected_ports),
    )


def revalidate_plan(
    plan: ServiceRestartPlan,
    current_profile_version: int,
    current_identity: str,
    current_graph: str,
    current_ports: Sequence[str],
    current_health_ok: bool,
    now: float,
) -> PlanRevalidation:
    """Re-check plan binding against current reality. Drift -> revalidate."""
    if plan.expires_at and now > plan.expires_at:
        return PlanRevalidation.EXPIRED
    if current_profile_version != plan.profile_version_bound:
        return PlanRevalidation.REVALIDATE_REQUIRED
    if current_identity != plan.identity_fingerprint:
        return PlanRevalidation.REVALIDATE_REQUIRED
    if current_graph != plan.graph_digest:
        return PlanRevalidation.REVALIDATE_REQUIRED
    if tuple(current_ports) != tuple(plan.ports):
        return PlanRevalidation.REVALIDATE_REQUIRED
    if not current_health_ok:
        return PlanRevalidation.REVALIDATE_REQUIRED
    return PlanRevalidation.VALID


__all__ = [
    "PlanRevalidation",
    "ServiceRestartPlan",
    "build_restart_plan",
    "revalidate_plan",
]