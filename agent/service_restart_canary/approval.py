"""Sprint 1.3.13 — single aux service restart canary (approval).

Every live restart requires explicit operator approval, bound to the full
contract (service/profile/operation/old identity/graph/ports/config/pre-health/
risk/blast/quiescence/startup/rollback/baseline/plan hash/TTL). Single-use.
Drift invalidates approval.
"""
from __future__ import annotations

import hashlib
import time

from .models import RestartApproval


def plan_hash_of(approval: RestartApproval) -> str:
    raw = "|".join([
        approval.service_id, str(approval.profile_version), approval.operation,
        approval.old_pid_identity, approval.old_start_identity, approval.graph_digest,
        repr(tuple(approval.ports)), approval.config_hash, approval.pre_health,
        approval.risk, approval.blast_radius, approval.quiescence_contract,
        approval.startup_contract, approval.rollback_plan, approval.baseline_sha,
    ])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class ApprovalManager:
    def __init__(self) -> None:
        self._approvals: dict[str, RestartApproval] = {}
        self._seq = 0

    def create(self, approval: RestartApproval | None = None, **kw) -> RestartApproval:
        if approval is not None:
            a = approval
        else:
            self._seq += 1
            aid = kw.get("approval_id") or f"restart-approval-{self._seq}"
            a = RestartApproval(approval_id=aid,
                                **{k: v for k, v in kw.items() if k != "approval_id"})
        # bind plan hash at creation
        a = RestartApproval(
            approval_id=a.approval_id, service_id=a.service_id, profile_version=a.profile_version,
            operation=a.operation, old_pid_identity=a.old_pid_identity,
            old_start_identity=a.old_start_identity, graph_digest=a.graph_digest,
            ports=a.ports, config_hash=a.config_hash, pre_health=a.pre_health,
            risk=a.risk, blast_radius=a.blast_radius, quiescence_contract=a.quiescence_contract,
            startup_contract=a.startup_contract, rollback_plan=a.rollback_plan,
            baseline_sha=a.baseline_sha, plan_hash=plan_hash_of(a),
            ttl=a.ttl, created_at=a.created_at or time.time(),
            used=False, transaction_id=a.transaction_id,
        )
        self._approvals[a.approval_id] = a
        return a

    def get(self, approval_id: str) -> RestartApproval | None:
        return self._approvals.get(approval_id)

    def validate(
        self,
        approval_id: str,
        service_id: str,
        operation: str = "RESTART",
        old_identity: str = "",
        old_start: str = "",
        graph_digest: str = "",
        config_hash: str = "",
        pre_health: str = "HEALTHY",
        now: float | None = None,
    ) -> tuple[bool, str]:
        """Single-use bound validation. Drift/expiry -> invalid."""
        now = now if now is not None else time.time()
        a = self._approvals.get(approval_id)
        if a is None:
            return False, "approval_missing"
        if a.used:
            return False, "approval_used"
        if a.operation != operation:
            return False, "approval_wrong_operation"
        if a.service_id != service_id:
            return False, "approval_wrong_service"
        if a.old_pid_identity != old_identity or a.old_start_identity != old_start:
            return False, "approval_identity_drift"
        if a.graph_digest != graph_digest:
            return False, "approval_graph_drift"
        if a.config_hash != config_hash:
            return False, "approval_config_drift"
        if a.pre_health != pre_health:
            return False, "approval_prehealth_drift"
        if now - a.created_at > a.ttl:
            return False, "approval_expired"
        return True, "approval_valid"

    def consume(self, approval_id: str) -> bool:
        a = self._approvals.get(approval_id)
        if a is None or a.used:
            return False
        self._approvals[approval_id] = RestartApproval(
            approval_id=a.approval_id, service_id=a.service_id,
            profile_version=a.profile_version, operation=a.operation,
            old_pid_identity=a.old_pid_identity, old_start_identity=a.old_start_identity,
            graph_digest=a.graph_digest, ports=a.ports, config_hash=a.config_hash,
            pre_health=a.pre_health, risk=a.risk, blast_radius=a.blast_radius,
            quiescence_contract=a.quiescence_contract, startup_contract=a.startup_contract,
            rollback_plan=a.rollback_plan, baseline_sha=a.baseline_sha, plan_hash=a.plan_hash,
            ttl=a.ttl, created_at=a.created_at, used=True, transaction_id=a.transaction_id,
        )
        return True


__all__ = ["ApprovalManager", "plan_hash_of"]