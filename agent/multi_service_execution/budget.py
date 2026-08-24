"""Sprint 1.3.17 — aggregate execution budget (§16)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionBudgetLimits:
    max_services: int = 3
    max_simulated_successes: int = 10_000
    max_attempts: int = 1000
    max_unknown_outcomes: int = 100
    max_compensations: int = 100


@dataclass(frozen=True, slots=True)
class BudgetVerdict:
    allowed: bool
    reason: str


class ExecutionBudget:
    """Durable aggregate execution budget.  No double reserve / consume."""

    def __init__(self, limits: ExecutionBudgetLimits | None = None) -> None:
        self.limits = limits or ExecutionBudgetLimits()
        self._reserved: dict[str, bool] = {}

    def reserve(self, planning_id: str, services: int) -> BudgetVerdict:
        if planning_id in self._reserved:
            return BudgetVerdict(False, "already-reserved")
        if services > self.limits.max_services:
            return BudgetVerdict(False, f"too-many-services:{services}>max")
        self._reserved[planning_id] = True
        return BudgetVerdict(True, "reserved")

    def consume(self, planning_id: str) -> BudgetVerdict:
        if planning_id not in self._reserved:
            return BudgetVerdict(False, "not-reserved")
        if not self._reserved[planning_id]:
            return BudgetVerdict(False, "already-consumed")
        self._reserved[planning_id] = False
        return BudgetVerdict(True, "consumed")

    def release(self, planning_id: str) -> BudgetVerdict:
        if planning_id not in self._reserved:
            return BudgetVerdict(False, "not-reserved")
        if self._reserved[planning_id] is False:
            return BudgetVerdict(False, "cannot-release-consumed")
        self._reserved[planning_id] = False
        return BudgetVerdict(True, "released")

    def is_reserved(self, planning_id: str) -> bool:
        return self._reserved.get(planning_id, False)


__all__ = ["BudgetVerdict", "ExecutionBudget", "ExecutionBudgetLimits"]