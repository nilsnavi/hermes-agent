"""Sprint 1.3.15 — immutable multi-service plan construction.

Builds a MultiServiceChangePlan from a bounded service set + verified graph.
Freezes execution/rollback order from topological order; validates the caller's
desired order; enforces risk monotonicity and blast-radius ceilings; computes
the plan hash.  After construction the plan must never be mutated.
"""
from __future__ import annotations

import secrets
import time
from collections.abc import Mapping

from .eligibility import ChildVerdict
from .graph import DependencyGraph, rollback_order, topological_order, validate_desired_order
from .models import MultiServiceChangePlan, ServiceSubPlan
from .registry import CoordinationRegistry
from .risk import acceptable_blast, risk_monotonic

# allowed shadow blast values (HOST/NETWORK/UNKNOWN => DENY)
ALLOWED_BLAST = {"RESOURCE", "SERVICE", "MULTI_SERVICE"}


class PlanBuilder:
    """Pure plan constructor.  All validation happens here, before any lock."""

    def __init__(
        self,
        registry: CoordinationRegistry,
        baseline_sha: str,
        coordinator_version: str = "0.1.0",
        *,
        clock=lambda: time.time(),
    ) -> None:
        self.registry = registry
        self.baseline_sha = baseline_sha
        self.coordinator_version = coordinator_version
        self.clock = clock

    def build(
        self,
        transaction_id: str,
        subplans: list[ServiceSubPlan],
        graph: DependencyGraph,
        desired_order: list[str] | None = None,
        *,
        approval_binding: str = "",
        budget_binding: str = "",
        health_contract_digest: str = "",
        ttl: float = 60.0,
    ) -> tuple[MultiServiceChangePlan, str | None]:
        """Returns (plan, None) on success or (None, reason) on failure."""
        if len(subplans) > self.registry.MAX_SERVICES:
            return None, "TOO_MANY_SERVICES"
        sids = [sp.service_id for sp in subplans]
        if len(set(sids)) != len(sids):
            return None, "DUPLICATE_SERVICE"
        if set(sids) != set(graph.service_ids):
            return None, "SERVICE_SET_GRAPH_MISMATCH"
        for sp in subplans:
            # self-control and hard-deny MUST be checked before registry
            # membership so gateway/scheduler/provider/... resolve to DENY even
            # though they are not synthetic-registry members.
            if self.registry.is_self_control(sp.service_id):
                return None, "SELF_CONTROL_FORBIDDEN"
            if self.registry.is_hard_denied(sp.service_id):
                return None, "HARD_DENIED_SERVICE"
            if not self.registry.is_registered(sp.service_id):
                return None, "UNREGISTERED_SERVICE"
            if sp.blast_radius not in ALLOWED_BLAST:
                return None, "BLAST_RADIUS_DENIED"

        verified = graph.validated(self.registry)
        if verified.status.value != "VALID":
            return None, verified.status.value  # CYCLE / UNKNOWN_DEPENDENCY / ...

        topo = topological_order(verified)
        if topo is None:
            return None, "CYCLE"
        exec_order = [sid for sid in topo if sid in set(sids)]

        if desired_order is not None:
            violation = validate_desired_order(verified, list(desired_order))
            if violation is not None:
                return None, violation

        rollback = rollback_order(verified, exec_order)

        risk_after = max((sp.risk for sp in subplans), key=lambda r: _risk_rank(r))
        if not risk_monotonic([sp.risk for sp in subplans]):
            return None, "RISK_DECREASED_INVALID"

        # parent blast = max(child) with dependency amplification
        parent_blast = _parent_blast([sp.blast_radius for sp in subplans])
        if not acceptable_blast(parent_blast):
            return None, "BLAST_RADIUS_DENIED"

        now = self.clock()
        plan = MultiServiceChangePlan(
            plan_id=f"plan-{secrets.token_hex(8)}",
            transaction_id=transaction_id,
            baseline_sha=self.baseline_sha,
            coordinator_version=self.coordinator_version,
            created_at=now,
            expires_at=now + ttl,
            service_set=tuple(subplans),
            dependency_graph_digest=verified.compute_digest() or graph.compute_digest(),
            execution_order=tuple(exec_order),
            rollback_order=tuple(rollback),
            operation_set=tuple(sp.operation for sp in subplans),
            risk_before=max((sp.risk for sp in subplans), key=_risk_rank),
            risk_after=risk_after,
            blast_radius=parent_blast,
            approval_binding=approval_binding,
            budget_binding=budget_binding,
            registry_digest=self.registry.registry_digest,
            health_contract_digest=health_contract_digest,
        )
        # freeze: compute hash over the immutable fields
        h = plan.compute_hash()
        return MultiServiceChangePlan(
            plan_id=plan.plan_id,
            transaction_id=plan.transaction_id,
            baseline_sha=plan.baseline_sha,
            coordinator_version=plan.coordinator_version,
            created_at=plan.created_at,
            expires_at=plan.expires_at,
            service_set=plan.service_set,
            dependency_graph_digest=plan.dependency_graph_digest,
            execution_order=plan.execution_order,
            rollback_order=plan.rollback_order,
            operation_set=plan.operation_set,
            risk_before=plan.risk_before,
            risk_after=plan.risk_after,
            blast_radius=plan.blast_radius,
            approval_binding=plan.approval_binding,
            budget_binding=plan.budget_binding,
            registry_digest=plan.registry_digest,
            health_contract_digest=plan.health_contract_digest,
            plan_hash=h,
        ), None


def _risk_rank(risk: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}.get(risk, 3)


def _parent_blast(child_blasts: list[str], amplify: bool = False) -> str:
    if not child_blasts:
        return "UNKNOWN"
    # dependency amplification: coordinating more than one service is inherently
    # a MULTI_SERVICE blast (parent blast = max(child) + coupling amplification).
    if amplify or len(child_blasts) > 1:
        return "MULTI_SERVICE"
    if any(b == "MULTI_SERVICE" for b in child_blasts):
        return "MULTI_SERVICE"
    if any(b == "SERVICE" for b in child_blasts):
        return "SERVICE"
    return "RESOURCE"


__all__ = ["ALLOWED_BLAST", "PlanBuilder"]