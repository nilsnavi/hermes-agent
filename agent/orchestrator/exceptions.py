"""Orchestrator exceptions (Sprint 1.0.5)."""

from agent.execution.exceptions import ExecutionErrorBase


class OrchestratorErrorBase(ExecutionErrorBase):
    """Base class for orchestrator-layer errors."""


class BudgetExceeded(OrchestratorErrorBase):
    """A hard execution budget was exhausted (steps / tools / replans /
    failures / runtime). Carries the offending limit name."""

    def __init__(self, limit: str) -> None:
        super().__init__(f"budget exceeded: {limit}")
        self.limit = limit


class PlanValidationError(OrchestratorErrorBase):
    """Plan failed validation — no tool may execute."""

    def __init__(self, issues) -> None:
        self.issues = list(issues)
        super().__init__("plan invalid: " + "; ".join(self.issues))


class OrchestrationRefused(OrchestratorErrorBase):
    """An operation was refused (e.g. approve on a terminal run)."""


__all__ = [
    "OrchestratorErrorBase",
    "BudgetExceeded",
    "PlanValidationError",
    "OrchestrationRefused",
]
