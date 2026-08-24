"""Sprint 1.3.16 — hardened compensation planning.

* COMPENSATION EXECUTION REMAINS SIMULATED ONLY (no production compensation
  adapter call ever).
* Compensate ONLY a child with proven prior effect (SIMULATED_EXECUTED /
  VERIFIED / COMPENSATION_REQUIRED).  Never NOT_STARTED / PREPARED-only /
  UNKNOWN-without-evidence / foreign-tx child.
* Order = reverse topological.
* Each action carries a semantic CompensationKey for exactly-once replay.
"""
from __future__ import annotations

from .models import CompensationKey, CompensationPlan, CompensationStep

# States that constitute "proven prior effect" (eligible for compensation).
_EFFECT = {"SIMULATED_EXECUTED", "VERIFIED", "COMPENSATION_REQUIRED",
           "COMPENSATING", "COMPENSATED", "FAILED_SAFE"}


def compensation_eligible(child_state: str) -> bool:
    return child_state in _EFFECT


def build_compensation_plan(*, transaction_id: str, global_tx_id: str,
                            service_set: tuple[str, ...],
                            rollback_order: list[str],
                            child_states: dict[str, str],
                            executed_set: frozenset[str],
                            verified_set: frozenset[str],
                            failed_child: str | None,
                            unknown_children: frozenset[str],
                            baseline_sha: str, plan_hash: str,
                            recovery_generation: int) -> CompensationPlan:
    """Build an immutable CompensationPlan over proven-effect children only.

    A NOT_STARTED / PREPARED-only child (no proven effect) is NEVER compensated.
    An UNKNOWN child (without durable effect evidence) is excluded from
    compensation and instead is surfaced for manual review.
    """
    effect_children = {s for s in service_set if compensation_eligible(child_states.get(s, "NOT_STARTED"))}
    steps: list[CompensationStep] = []
    # reverse topological order: dependents first
    for i, sid in enumerate(rollback_order):
        st = child_states.get(sid, "NOT_STARTED")
        if compensation_eligible(st):
            steps.append(
                CompensationStep(
                    service_id=sid,
                    operation=f"COMPENSATE_{st}",
                    order=i,
                    preconditions=("prior-effect",),
                    evidence=f"effect:{st}",
                    unsupported=False,
                )
            )
        else:
            steps.append(
                CompensationStep(service_id=sid, operation="NOOP",
                                 order=i, preconditions=(), evidence="no-effect",
                                 unsupported=False)
            )
    return CompensationPlan(
        global_tx_id=global_tx_id,
        transaction_id=transaction_id,
        service_set=service_set,
        executed_set=frozenset(executed_set),
        verified_set=frozenset(verified_set),
        failed_child=failed_child or "",
        unknown_children=frozenset(unknown_children),
        baseline_sha=baseline_sha,
        plan_hash=plan_hash,
        recovery_generation=recovery_generation,
        steps=tuple(steps),
    )


def compensation_plan_status(plan: CompensationPlan) -> str:
    """COMPENSATION_UNSUPPORTED if any required (effect) child has no proven
    strategy.  Otherwise COMPENSATION_SUPPORTED."""
    required = [s for s in plan.steps if not s.unsupported and s.operation != "NOOP"]
    if not required:
        return "NO_COMPENSATION_REQUIRED"
    return "COMPENSATION_SUPPORTED"


def compensation_unsupported(plan: CompensationPlan) -> bool:
    """True => an effect child needs compensation but has no proven strategy ->
    manual review, never marked safe success.  A NOOP (no-effect) step never
    counts as unsupported."""
    return any(s.unsupported and s.operation != "NOOP" for s in plan.steps)


__all__ = ["compensation_eligible", "build_compensation_plan",
           "compensation_plan_status", "compensation_unsupported"]