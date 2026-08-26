from __future__ import annotations

from collections import deque
from collections.abc import Set as SetABC
from typing import AbstractSet

from .models import TaskPlan, TaskStep


class InvalidTaskGraph(ValueError):
    """Raised when a task plan cannot form a valid dependency graph."""


_MAX_ID_LENGTH = 65_536


def _validate_execution_ids(name: str, values: object) -> frozenset[str]:
    if not isinstance(values, SetABC) or isinstance(values, (str, bytes)):
        raise InvalidTaskGraph(f"{name} must be a set-like collection of step IDs")
    normalized: set[str] = set()
    for value in values:
        if type(value) is not str or not value.strip():
            raise InvalidTaskGraph(f"{name} must contain non-empty string step IDs")
        if len(value) > _MAX_ID_LENGTH:
            raise InvalidTaskGraph(
                f"{name} step IDs exceed the {_MAX_ID_LENGTH}-character limit"
            )
        normalized.add(value)
    return frozenset(normalized)


class TaskGraph:
    """Validated dependency graph for the steps in one task plan."""

    def __init__(self, plan: TaskPlan) -> None:
        if type(plan) is not TaskPlan:
            raise InvalidTaskGraph("plan must be an exact TaskPlan contract")
        self._plan = plan
        step_ids = [step.id for step in plan.steps]
        if len(set(step_ids)) != len(step_ids):
            raise InvalidTaskGraph("duplicate step IDs are not allowed")
        known_step_ids = set(step_ids)
        for step in plan.steps:
            for field in ("task_id", "tenant_id", "user_id"):
                if getattr(step, field) != getattr(plan, field):
                    raise InvalidTaskGraph(
                        f"step {step.id!r} has mismatched {field}"
                    )
            if step.id in step.dependencies:
                raise InvalidTaskGraph(f"step {step.id!r} cannot depend on itself")
            missing = step.dependencies - known_step_ids
            if missing:
                missing_ids = ", ".join(sorted(missing))
                raise InvalidTaskGraph(
                    f"step {step.id!r} has missing dependencies: {missing_ids}"
                )

        remaining_dependencies = {
            step.id: set(step.dependencies) for step in plan.steps
        }
        dependents = {step_id: set() for step_id in known_step_ids}
        for step in plan.steps:
            for dependency in step.dependencies:
                dependents[dependency].add(step.id)
        ready = deque(
            step_id
            for step_id, dependencies in remaining_dependencies.items()
            if not dependencies
        )
        visited = 0
        while ready:
            step_id = ready.popleft()
            visited += 1
            for dependent in dependents[step_id]:
                remaining_dependencies[dependent].remove(step_id)
                if not remaining_dependencies[dependent]:
                    ready.append(dependent)
        if visited != len(plan.steps):
            raise InvalidTaskGraph("dependency cycle detected")

        self._steps = tuple(sorted(plan.steps, key=lambda step: step.id))
        self._step_ids = frozenset(known_step_ids)

    def ready_nodes(
        self,
        *,
        completed: AbstractSet[str] = frozenset(),
        in_flight: AbstractSet[str] = frozenset(),
    ) -> tuple[TaskStep, ...]:
        """Return runnable steps in stable ID order."""
        completed_ids = _validate_execution_ids("completed", completed)
        in_flight_ids = _validate_execution_ids("in_flight", in_flight)
        overlap = completed_ids & in_flight_ids
        if overlap:
            overlap_ids = ", ".join(sorted(overlap))
            raise InvalidTaskGraph(
                f"completed and in_flight execution state IDs overlap: {overlap_ids}"
            )
        unknown = (completed_ids | in_flight_ids) - self._step_ids
        if unknown:
            unknown_ids = ", ".join(sorted(unknown))
            raise InvalidTaskGraph(f"unknown execution state IDs: {unknown_ids}")
        unavailable = completed_ids | in_flight_ids
        return tuple(
            step
            for step in self._steps
            if step.id not in unavailable and step.dependencies <= completed_ids
        )
