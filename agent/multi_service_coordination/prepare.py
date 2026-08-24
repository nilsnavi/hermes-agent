"""Sprint 1.3.15 — prepare phase.

For every child: identity verify, registry verify, config verify, dependency
verify, blast verify, risk verify, consumer verify, pre-health, rollback proof,
budget reservation, approval validation, idempotency claim.  Only after ALL
children are PREPARED does the parent become PREPARED.
"""
from __future__ import annotations

import secrets
import time

from .models import PreparedServiceToken, ServiceSubPlan


class PrepareVerdict:
    def __init__(self, prepared: bool, reason: str | None = None) -> None:
        self.prepared = prepared
        self.reason = reason


def prepare_service(
    service_id: str,
    subplan: ServiceSubPlan,
    txid: str,
    generation: int,
    registry,
    *,
    identity_verified=True,
    config_valid=True,
    dependency_healthy=True,
    blast_acceptable=True,
    risk_acceptable=True,
    consumer_known=True,
    pre_health_ok=True,
    rollback_proven=True,
    approval_valid=True,
    budget_available=True,
    idempotency_claimable=True,
    now: float | None = None,
    expires_at: float | None = None,
    clock=lambda: time.time(),
) -> tuple[PreparedServiceToken | None, PrepareVerdict]:
    """Returns (token, verdict).  Token is None unless EVERY gate passes."""
    gates = [
        ("IDENTITY_UNVERIFIED", identity_verified),
        ("REGISTRY_UNKNOWN", registry.is_registered(service_id)),
        ("SELF_CONTROL_FORBIDDEN", not registry.is_self_control(service_id)),
        ("HARD_DENIED", not registry.is_hard_denied(service_id)),
        ("CONFIG_INVALID", config_valid),
        ("DEPENDENCY_UNHEALTHY", dependency_healthy),
        (
            "BLAST_DENIED",
            blast_acceptable and subplan.blast_radius in {"RESOURCE", "SERVICE", "MULTI_SERVICE"},
        ),
        ("RISK_DENIED", risk_acceptable),
        ("CONSUMER_UNKNOWN", consumer_known),
        ("PRE_HEALTH_FAILED", pre_health_ok),
        ("ROLLBACK_UNPROVEN", rollback_proven),
        ("APPROVAL_INVALID", approval_valid),
        ("BUDGET_UNAVAILABLE", budget_available),
        ("IDEMPOTENCY_UNCLAIMABLE", idempotency_claimable),
    ]
    now = clock() if now is None else now
    for reason, ok in gates:
        if not ok:
            return None, PrepareVerdict(False, reason)
    token = PreparedServiceToken(
        token_id=f"token-{secrets.token_hex(10)}",
        global_tx_id=txid,
        service_transaction_id=f"{txid}+{service_id}+{generation}",
        plan_hash="",
        service_id=service_id,
        profile_version=subplan.service_profile_version,
        registry_digest=registry.registry_digest,
        identity_fingerprint=subplan.identity_fingerprint,
        config_fingerprint=subplan.config_fingerprint,
        dependency_digest=subplan.dependency_digest,
        approval_reference=subplan.approval_reference,
        budget_reference=subplan.budget_reference,
        lock_nonce=secrets.token_hex(12),
        pre_health=subplan.pre_health,
        required_post_health=subplan.required_post_health,
        risk=subplan.risk,
        blast_radius=subplan.blast_radius,
        expires_at=(now + 30.0) if expires_at is None else expires_at,
        generation=generation,
    )
    return token, PrepareVerdict(True)


__all__ = ["PrepareVerdict", "prepare_service"]