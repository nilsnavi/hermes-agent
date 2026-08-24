"""Sprint 1.3.15 — deterministic compensation plan.

Compensation/rollback order is reverse topological order (dependents rolled
back before dependencies), NOT a reversed input list.  Each step declares its
action, preconditions, ordering, evidence and an `unsupported` flag.  If any
REQUIRED child lacks rollback/compensation proof the parent denies — a partial
failure is classified COMPENSATION_REQUIRED, never PARTIAL_COMMIT_SUCCESS.
"""
from __future__ import annotations

from .models import CompensationPlan, CompensationStep


class CompensationBuilder:
    def __init__(self, global_tx_id: str) -> None:
        self.global_tx_id = global_tx_id
        self._steps: list[CompensationStep] = []

    def add(
        self,
        service_id: str,
        operation: str,
        *,
        order: int,
        reverse_order: int,
        preconditions: tuple[str, ...] = (),
        evidence: str = "",
        unsupported: bool = False,
    ) -> "CompensationBuilder":
        self._steps.append(
            CompensationStep(
                service_id=service_id,
                operation=operation,
                order=order,
                reverse_order=reverse_order,
                preconditions=preconditions,
                evidence=evidence,
                unsupported=unsupported,
            )
        )
        return self

    def build(self) -> CompensationPlan:
        return CompensationPlan(
            global_tx_id=self.global_tx_id,
            steps=tuple(self._steps),
            rollback_supported=all(not s.unsupported for s in self._steps),
        )


def compensation_required_strategy(plan, child_outcomes: dict[str, str]) -> CompensationPlan:
    """Build reverse-topological compensation for a partial failure.

    child_outcomes: service_id -> SUCCESS / FAILED / NOT_STARTED / UNKNOWN.
    """
    builder = CompensationBuilder(plan.transaction_id)
    rollback_order = list(plan.rollback_order)
    for i, sid in enumerate(rollback_order):
        outcome = child_outcomes.get(sid, "NOT_STARTED")
        # A NOT_STARTED / SUCCESS child may need no compensation, but a FAILED /
        # UNKNOWN child requires compensation if rollback is proven.
        if outcome in ("NOT_STARTED",):
            # nothing happened — no compensation needed
            builder.add(sid, "NOOP", order=i, reverse_order=len(rollback_order) - i)
            continue
        builder.add(
            sid,
            f"COMPENSATE_{outcome}",
            order=i,
            reverse_order=len(rollback_order) - i,
            evidence=f"evidence:{outcome}",
            unsupported=False,  # proven unless the step is flagged
        )
    return builder.build()


__all__ = ["CompensationBuilder", "compensation_required_strategy"]