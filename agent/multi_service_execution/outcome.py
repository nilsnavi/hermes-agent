"""Sprint 1.3.17 — adapter outcome normalization (§11).

The central hard rule: ``ADAPTER_SUCCEEDED`` NEVER maps directly to
``COMMITTED``.  An adapter success only elevates a child to
``CHILD_SIMULATED_SUCCEEDED``; global success additionally requires
post-execution verification + stabilization + coordinator-owned commit.
"""
from __future__ import annotations

from .fake_adapter import FakeAdapterResult
from .models import AdapterOutcome, ChildExecutionState


def adapter_outcome_to_child_state(result: FakeAdapterResult) -> ChildExecutionState:
    """Map a single adapter result to the child state.  Fail closed on any
    non-success; an adapter success never implies committed."""
    if result.outcome == AdapterOutcome.ADAPTER_SUCCEEDED:
        return ChildExecutionState.CHILD_SIMULATED_SUCCEEDED
    if result.outcome == AdapterOutcome.ADAPTER_FAILED:
        return ChildExecutionState.CHILD_SIMULATED_FAILED
    # UNKNOWN and anything unclassifiable -> unknown (never safe)
    return ChildExecutionState.CHILD_SIMULATED_UNKNOWN


def normalize_adapter_result(result: FakeAdapterResult) -> FakeAdapterResult:
    """Ensure the result is a valid FakeAdapterResult; fail closed otherwise."""
    if not isinstance(result, FakeAdapterResult):
        return FakeAdapterResult(
            outcome=AdapterOutcome.ADAPTER_UNKNOWN_OUTCOME, error="invalid adapter result type"
        )
    return result


__all__ = [
    "adapter_outcome_to_child_state",
    "normalize_adapter_result",
]