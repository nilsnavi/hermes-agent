"""Planner.

The Planner compiles a TaskAnalysis into a versioned TaskPlan with a DAG of
TaskSteps. It produces a plan only; it never executes steps, never grants
execution authority, and never dispatches to agents. The resulting plan is
validated (shape, cycle, capability presence) and can be rejected if it cannot
honour a declared capability — but rejection is a planning decision, not an
authorization denial of any execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet

from .analyzer import TaskAnalysis
from .models import TaskPlan, TaskStep
from .task_graph import InvalidTaskGraph, TaskGraph

MAX_STEPS = 64


class InvalidPlan(ValueError):
    """Raised when a proposed plan violates planner constraints."""


@dataclass(frozen=True, slots=True)
class PlannedStep:
    step_id: str
    goal: str
    required_capabilities: tuple[str, ...]
    dependencies: AbstractSet[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.step_id, str) or not self.step_id.strip():
            raise InvalidPlan("step_id must be a non-empty string")
        if not isinstance(self.goal, str) or not self.goal.strip():
            raise InvalidPlan("goal must be a non-empty string")
        if not isinstance(self.required_capabilities, tuple) or not self.required_capabilities:
            raise InvalidPlan("required_capabilities must be a non-empty tuple")
        if not isinstance(self.dependencies, frozenset):
            object.__setattr__(self, "dependencies", frozenset(self.dependencies))


class Planner:
    """Pure planner: analysis -> validated TaskPlan. No execution surface."""

    @staticmethod
    def plan(
        analysis: TaskAnalysis,
        *,
        plan_id: str,
        tenant_id: str,
        user_id: str,
        steps: tuple[PlannedStep, ...],
        available_capabilities: AbstractSet[str] | None = None,
    ) -> TaskPlan:
        if type(analysis) is not TaskAnalysis:
            raise InvalidPlan("analysis must be an exact TaskAnalysis value")
        for name, value in (
            ("plan_id", plan_id),
            ("tenant_id", tenant_id),
            ("user_id", user_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise InvalidPlan(f"{name} must be a non-empty string")
        if not isinstance(steps, tuple) or not steps:
            raise InvalidPlan("plan requires at least one step")
        if len(steps) > MAX_STEPS:
            raise InvalidPlan(f"plan exceeds {MAX_STEPS} steps")
        if available_capabilities is not None and isinstance(
            available_capabilities, (str, bytes)
        ):
            raise InvalidPlan("available_capabilities must be a set-like collection")

        # Capability gate: reject a plan that demands an unavailable capability.
        if available_capabilities is not None:
            available = set(available_capabilities)
            for step in steps:
                missing = set(step.required_capabilities) - available
                if missing:
                    missing_names = ", ".join(sorted(missing))
                    raise InvalidPlan(
                        f"step {step.step_id!r} requires unavailable "
                        f"capabilities: {missing_names}"
                    )

        model_steps = tuple(
            TaskStep(
                id=step.step_id,
                task_id=analysis.task_id,
                tenant_id=tenant_id,
                user_id=user_id,
                dependencies=frozenset(step.dependencies),
            )
            for step in steps
        )
        plan = TaskPlan(
            id=plan_id,
            task_id=analysis.task_id,
            tenant_id=tenant_id,
            user_id=user_id,
            steps=model_steps,
        )
        # Validate the DAG (duplicates, cycles, missing deps, scope mismatch).
        TaskGraph(plan)
        return plan