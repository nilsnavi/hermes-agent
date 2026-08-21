"""Sprint 1.3.13 — single aux service restart canary (preflight).

Typed preflight immediately before adapter: allowlist, identity, old process
identity, cgroup, executable, user, graph, blast, dependents, unchanged config,
pre-health, correct port ownership, no orphan children, budget, breaker,
approval valid, plan fresh. Repeated immediately before adapter.
"""
from __future__ import annotations

from dataclasses import dataclass

from .breaker import RestartCircuitBreaker
from .budget import RestartBudget
from .approval import ApprovalManager


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    reason: str = ""


class RestartPreflight:
    def __init__(self, budget: RestartBudget, breaker: RestartCircuitBreaker,
                 approvals: ApprovalManager | None = None) -> None:
        self._budget = budget
        self._breaker = breaker
        self._approvals = approvals

    def run(
        self,
        *,
        service_id: str,
        unit_identity_ok: bool,
        old_pid_identity: str,
        old_start_identity: str,
        identity_verified: bool,
        graph_healthy: bool,
        blast_radius: str,
        dependents_count: int,
        config_unchanged: bool,
        pre_health_ok: bool,
        port_ownership_ok: bool,
        no_orphan_children: bool,
        executable_ok: bool,
        user_ok: bool,
        cgroup_ok: bool,
        plan_fresh: bool,
        approval_valid: bool,
    ) -> PreflightResult:
        # budget available
        if self._budget.remaining_attempts() < 1:
            return PreflightResult(False, "budget_exhausted")
        # breaker closed
        if self._breaker.open():
            return PreflightResult(False, "breaker_open")
        if not unit_identity_ok:
            return PreflightResult(False, "unit_identity_mismatch")
        if not old_pid_identity or not old_start_identity:
            return PreflightResult(False, "old_identity_missing")
        if not identity_verified:
            return PreflightResult(False, "identity_unverified")
        if not graph_healthy:
            return PreflightResult(False, "graph_unhealthy")
        if blast_radius != "SERVICE":
            return PreflightResult(False, "blast_not_service")
        if dependents_count > 0:
            return PreflightResult(False, "dependents_present")
        if not config_unchanged:
            return PreflightResult(False, "config_changed")
        if not pre_health_ok:
            return PreflightResult(False, "prehealth_bad")
        if not port_ownership_ok:
            return PreflightResult(False, "port_ownership_wrong")
        if not no_orphan_children:
            return PreflightResult(False, "orphan_children")
        if not (executable_ok and user_ok and cgroup_ok):
            return PreflightResult(False, "identity_attr_mismatch")
        if not plan_fresh:
            return PreflightResult(False, "plan_stale")
        if approval_valid is not True:
            return PreflightResult(False, "approval_invalid")
        return PreflightResult(True)


__all__ = ["PreflightResult", "RestartPreflight"]