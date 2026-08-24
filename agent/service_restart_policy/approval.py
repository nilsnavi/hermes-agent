"""Durable, fully bound, single-use operator approval."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ._durable import JsonTransaction, require_finite_time


@dataclass(frozen=True)
class ApprovalContract:
    approval_id: str
    service_id: str
    profile_version: int
    transaction_id: str
    old_process_identity: str
    graph_digest: str
    consumer_state: str
    config_digest: str
    health_digest: str
    risk: str
    blast: str
    quiescence_contract: str
    startup_contract: str
    recovery_contract: str
    budget_snapshot: str
    breaker_snapshot: str
    plan_hash: str
    baseline_sha: str
    expires_at: float
    plan_expires_at: float | None = None
    registry_digest: str = ""

    def binding(self) -> dict:
        data = asdict(self)
        data.pop("approval_id")
        data.pop("expires_at")
        return data


class DurableApprovalStore:
    def __init__(self, root) -> None:
        self._tx = JsonTransaction(root, "approvals")

    def issue_contract(self, contract: ApprovalContract) -> None:
        binding = contract.binding()
        expires_at = require_finite_time(contract.expires_at)
        plan_expires_at = require_finite_time(
            contract.expires_at if contract.plan_expires_at is None else contract.plan_expires_at
        )
        required_strings = (
            contract.approval_id,
            contract.service_id,
            contract.transaction_id,
            contract.old_process_identity,
            contract.graph_digest,
            contract.consumer_state,
            contract.config_digest,
            contract.health_digest,
            contract.risk,
            contract.blast,
            contract.quiescence_contract,
            contract.startup_contract,
            contract.recovery_contract,
            contract.budget_snapshot,
            contract.breaker_snapshot,
            contract.plan_hash,
            contract.baseline_sha,
        )
        if (
            contract.profile_version < 1
            or not all(isinstance(value, str) and bool(value.strip()) for value in required_strings)
            or expires_at <= 0
            or plan_expires_at <= 0
        ):
            raise ValueError("approval binding must be complete")

        def change(data):
            if contract.approval_id in data:
                raise ValueError("approval_id is immutable and cannot be reissued")
            data[contract.approval_id] = {
                "binding": binding,
                "expires_at": expires_at,
                "plan_expires_at": plan_expires_at,
                "used": False,
            }

        self._tx.update(change)

    @staticmethod
    def _contract_verdict(rec, contract: ApprovalContract, now: float) -> str:
        now = require_finite_time(now)
        if rec is None:
            return "APPROVAL_MISSING"
        if rec.get("used"):
            return "APPROVAL_USED"
        if rec.get("binding") != contract.binding():
            return "APPROVAL_BINDING_MISMATCH"
        try:
            expires_at = require_finite_time(rec.get("expires_at"))
            plan_expires_at = require_finite_time(rec.get("plan_expires_at"))
        except ValueError:
            return "APPROVAL_INVALID_STATE"
        if now > expires_at:
            return "APPROVAL_EXPIRED"
        if now > plan_expires_at:
            return "PLAN_EXPIRED"
        return "APPROVED"

    def validate_contract(self, contract: ApprovalContract, now: float) -> str:
        return self._contract_verdict(self._tx.read().get(contract.approval_id), contract, now)

    def consume_contract(self, contract: ApprovalContract, now: float) -> str:
        def change(data):
            rec = data.get(contract.approval_id)
            verdict = self._contract_verdict(rec, contract, now)
            if verdict != "APPROVED":
                return verdict
            rec["used"] = True
            rec["used_at"] = now
            return "APPROVED"

        return self._tx.update(change)

    def owns_consumed_contract(self, contract: ApprovalContract) -> bool:
        """Verify immutable binding and this contract's durable single-use consumption."""
        rec = self._tx.read().get(contract.approval_id)
        return bool(
            isinstance(rec, dict)
            and rec.get("used") is True
            and rec.get("binding") == contract.binding()
        )

    # Compatibility helpers for pre-1.3.14 callers. These remain tightly bound,
    # but the policy runtime uses ApprovalContract exclusively.
    def issue(
        self,
        approval_id: str,
        service_id: str,
        profile_version: int,
        transaction_id: str,
        graph_digest: str,
        identity_digest: str,
        expires_at: float,
    ) -> None:
        self.issue_contract(_legacy_contract(
            approval_id, service_id, profile_version, transaction_id,
            graph_digest, identity_digest, expires_at,
        ))

    def validate(
        self,
        approval_id: str,
        service_id: str,
        profile_version: int,
        transaction_id: str,
        graph_digest: str,
        identity_digest: str,
        now: float,
    ) -> str:
        return self.validate_contract(_legacy_contract(
            approval_id, service_id, profile_version, transaction_id,
            graph_digest, identity_digest, float("inf"),
        ), now)

    def consume(
        self,
        approval_id: str,
        service_id: str,
        profile_version: int,
        transaction_id: str,
        graph_digest: str,
        identity_digest: str,
        now: float,
    ) -> str:
        return self.consume_contract(_legacy_contract(
            approval_id, service_id, profile_version, transaction_id,
            graph_digest, identity_digest, float("inf"),
        ), now)


def _legacy_contract(
    approval_id: str,
    service_id: str,
    profile_version: int,
    transaction_id: str,
    graph_digest: str,
    identity_digest: str,
    expires_at: float,
) -> ApprovalContract:
    return ApprovalContract(
        approval_id=approval_id,
        service_id=service_id,
        profile_version=profile_version,
        transaction_id=transaction_id,
        old_process_identity=identity_digest,
        graph_digest=graph_digest,
        consumer_state="LEGACY_BOUND",
        config_digest="LEGACY_BOUND",
        health_digest="LEGACY_BOUND",
        risk="LEGACY_BOUND",
        blast="LEGACY_BOUND",
        quiescence_contract="LEGACY_BOUND",
        startup_contract="LEGACY_BOUND",
        recovery_contract="LEGACY_BOUND",
        budget_snapshot="LEGACY_BOUND",
        breaker_snapshot="LEGACY_BOUND",
        plan_hash="LEGACY_BOUND",
        baseline_sha="LEGACY_BOUND",
        expires_at=expires_at,
    )


class RestartApprovalPolicy(DurableApprovalStore):
    """Named full-contract, durable, single-use restart approval policy."""


__all__ = ["ApprovalContract", "DurableApprovalStore", "RestartApprovalPolicy"]
