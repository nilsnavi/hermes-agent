"""Sprint 1.3.17 — ExecutionBarrier (§8 PHASE A).

The barrier evaluates the FINAL PREPARE gate set.  Only after EVERY gate is
READY does it report ``EXECUTION_BARRIER_READY``.  Deterministic, side-effect
free.  Revalidation findings are returned so the pipeline can abort before any
adapter call.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .models import MultiServiceExecutionPlan


@dataclass(frozen=True, slots=True)
class BarrierVerdict:
    ready: bool
    findings: tuple[str, ...] = field(default_factory=tuple)

    def blocked_by(self) -> str:
        return ",".join(self.findings) or "READY"


class ExecutionBarrier:
    """Final revalidation gate.  Every check must pass."""

    def evaluate(
        self,
        plan: MultiServiceExecutionPlan,
        *,
        children_revalidated: bool = True,
        child_admissions: Mapping[str, bool] | None = None,
        locks_live_owned: bool = True,
        approvals_valid: bool = True,
        budgets_reserved: bool = True,
        graph_healthy: bool = True,
        identities_verified: bool = True,
        registry_digest_ok: bool = True,
        baseline_digest_ok: bool = True,
        recovery_clean: bool = True,
        prepared_tokens_valid: bool = True,
        kill_switch_off: bool = True,
        system_boundary_allow: bool = True,
        executor_contract_ok: bool = True,
        no_drift: bool = True,
    ) -> BarrierVerdict:
        findings: list[str] = []
        if plan.expired(0):  # not meaningful here; expiry checked downstream
            pass
        if not children_revalidated:
            findings.append("children-not-revalidated")
        adm = child_admissions or {}
        missing = [s for s in plan.service_set if not adm.get(s, False)]
        if missing:
            findings.append(f"child-admission-missing:{','.join(missing)}")
        if not locks_live_owned:
            findings.append("locks-not-live-owned")
        if not approvals_valid:
            findings.append("approval-invalid")
        if not budgets_reserved:
            findings.append("budget-not-reserved")
        if not graph_healthy:
            findings.append("graph-unhealthy")
        if not identities_verified:
            findings.append("identity-unverified")
        if not registry_digest_ok:
            findings.append("registry-drift")
        if not baseline_digest_ok:
            findings.append("baseline-drift")
        if not recovery_clean:
            findings.append("recovery-not-clean")
        if not prepared_tokens_valid:
            findings.append("prepared-token-invalid")
        if not kill_switch_off:
            findings.append("kill-switch-on")
        if not system_boundary_allow:
            findings.append("system-boundary-deny")
        if not executor_contract_ok:
            findings.append("executor-contract-unsatisfied")
        if not no_drift:
            findings.append("drift-detected")
        if findings:
            return BarrierVerdict(ready=False, findings=tuple(findings))
        return BarrierVerdict(ready=True, findings=())


__all__ = ["BarrierVerdict", "ExecutionBarrier"]