"""Sprint 1.3.17 — compensation bridge (§20).

Reuses the certified coordination compensation layer + recovery compensation.
If a simulated partial failure occurs we NEVER fake success: we set
``COMPENSATION_REQUIRED`` and build a CompensationPlan.

Compensation remains SIMULATED ONLY — there is no real compensation adapter.
The produced plan is pure data; nothing here executes a rollback.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent.multi_service_coordination.models import (
    CompensationPlan as CoordCompensationPlan,
    CompensationStep,
)

from .models import (
    ChildExecutionState,
    MultiServiceExecutionPlan,
)


@dataclass(frozen=True, slots=True)
class CompensationBridgeResult:
    compensation_required: bool
    plan: CoordCompensationPlan | None
    failed_children: tuple[str, ...]
    effect_children: tuple[str, ...]
    real_compensation_adapter_calls: int = 0


def _effect_eligible(state: ChildExecutionState) -> bool:
    return state in (
        ChildExecutionState.CHILD_SIMULATED_SUCCEEDED,
        ChildExecutionState.CHILD_VERIFIED,
        ChildExecutionState.CHILD_COMPENSATION_REQUIRED,
        ChildExecutionState.CHILD_TERMINAL,
    )


def build_compensation_bridge_result(
    plan: MultiServiceExecutionPlan,
    child_states: Mapping[str, ChildExecutionState],
    *,
    fail_child: str | None = None,
) -> CompensationBridgeResult:
    """Build a reverse-topological compensation plan over effect children."""
    failed: list[str] = []
    effect: list[str] = []
    for sid in plan.topological_order:
        st = child_states.get(sid, ChildExecutionState.CHILD_READY)
        if st in (ChildExecutionState.CHILD_SIMULATED_FAILED,
                  ChildExecutionState.CHILD_COMPENSATION_REQUIRED):
            failed.append(sid)
        if _effect_eligible(st):
            effect.append(sid)
    if not failed:
        return CompensationBridgeResult(False, None, (), tuple(effect))

    rollback = list(reversed(plan.topological_order))  # dependents first
    steps: list[CompensationStep] = []
    for i, sid in enumerate(rollback):
        steps.append(
            CompensationStep(
                service_id=sid,
                operation="COMPENSATE" if sid in effect else "NOOP",
                order=i,
                reverse_order=len(rollback) - i,
                preconditions=("prior-effect",) if sid in effect else (),
                evidence=f"effect:{str(child_states.get(sid, ChildExecutionState.CHILD_READY).value)}",
                unsupported=False,
            )
        )
    comp_plan = CoordCompensationPlan(
        global_tx_id=plan.global_tx_id, steps=tuple(steps), rollback_supported=True,
    )
    return CompensationBridgeResult(
        True, comp_plan, tuple(failed), tuple(effect),
        real_compensation_adapter_calls=0,
    )


__all__ = ["CompensationBridgeResult", "build_compensation_bridge_result"]