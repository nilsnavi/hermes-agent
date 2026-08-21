"""Sprint 1.3.13 — single aux service restart canary (plan).

Immutable ServiceRestartCanaryPlan binding identity/graph/config/health/approval
+ TTL. Drift / expiry -> invalid (approval drift caught by ApprovalManager; plan
freshness by expires_at).
"""
from __future__ import annotations

from .models import ServiceRestartCanaryPlan


def build_plan(
    *,
    transaction_id: str,
    service_id: str,
    profile_version: int,
    old_process_identity: str,
    identity_fingerprint: str,
    graph_digest: str,
    config_hash: str,
    ports_before: tuple,
    pre_health_receipt: str,
    approval_id: str,
    risk: str = "HIGH",
    blast_radius: str = "SERVICE",
    created_at: float,
    ttl: float = 300.0,
) -> ServiceRestartCanaryPlan:
    return ServiceRestartCanaryPlan(
        transaction_id=transaction_id,
        service_id=service_id,
        profile_version=profile_version,
        operation="RESTART",
        old_process_identity=old_process_identity,
        identity_fingerprint=identity_fingerprint,
        graph_digest=graph_digest,
        config_hash=config_hash,
        ports_before=tuple(ports_before),
        pre_health_receipt=pre_health_receipt,
        approval_id=approval_id,
        risk=risk,
        blast_radius=blast_radius,
        recovery_strategy="MANUAL_REVIEW_REQUIRED",
        created_at=created_at,
        expires_at=created_at + ttl,
    )


__all__ = ["build_plan"]