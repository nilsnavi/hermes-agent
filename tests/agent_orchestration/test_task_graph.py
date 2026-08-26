from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.agent_orchestration import (
    InvalidTaskGraph,
    TaskGraph,
    TaskPlan,
    TaskStep,
)


@pytest.mark.parametrize("model", ("step", "plan"))
@pytest.mark.parametrize("field", ("id", "task_id", "tenant_id", "user_id"))
def test_plan_and_step_reject_empty_identity(model: str, field: str) -> None:
    values = {
        "id": "item-1",
        "task_id": "task-1",
        "tenant_id": "tenant-a",
        "user_id": "user-a",
    }
    values[field] = "   "

    with pytest.raises(ValueError, match=field):
        if model == "step":
            TaskStep(
                id=values["id"],
                task_id=values["task_id"],
                tenant_id=values["tenant_id"],
                user_id=values["user_id"],
            )
        else:
            TaskPlan(
                id=values["id"],
                task_id=values["task_id"],
                tenant_id=values["tenant_id"],
                user_id=values["user_id"],
            )


def test_dag_contracts_reject_malformed_and_oversized_inputs() -> None:
    valid_identity = {
        "id": "step-a",
        "task_id": "task-1",
        "tenant_id": "tenant-a",
        "user_id": "user-a",
    }
    for bad_id in (1, True, "x" * 65_537):
        with pytest.raises(ValueError):
            TaskStep(**{**valid_identity, "id": bad_id})  # type: ignore[arg-type]

    for dependencies in ("step-a", ["step-a"], {""}, {1}):
        with pytest.raises(ValueError, match="dependencies"):
            TaskStep(**valid_identity, dependencies=dependencies)  # type: ignore[arg-type]

    valid_step = TaskStep(**valid_identity)
    for steps in ("step-a", [object()]):
        with pytest.raises(ValueError, match="steps"):
            TaskPlan(
                "plan-1", "task-1", "tenant-a", "user-a", steps=steps
            )  # type: ignore[arg-type]

    with pytest.raises(InvalidTaskGraph, match="TaskPlan"):
        TaskGraph(object())  # type: ignore[arg-type]

    assert TaskPlan(
        "plan-1", "task-1", "tenant-a", "user-a", steps=(step for step in [valid_step])
    ).steps == (valid_step,)


def test_plan_and_step_identity_are_immutable_and_scoped() -> None:
    step = TaskStep(
        id="step-a",
        task_id="task-1",
        tenant_id="tenant-a",
        user_id="user-a",
        dependencies={"step-root"},
    )
    plan = TaskPlan(
        id="plan-1",
        task_id="task-1",
        tenant_id="tenant-a",
        user_id="user-a",
        steps=[step],
    )

    assert step.dependencies == frozenset({"step-root"})
    assert plan.steps == (step,)
    assert (plan.tenant_id, plan.user_id) == ("tenant-a", "user-a")
    with pytest.raises(FrozenInstanceError):
        step.id = "replacement"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.id = "replacement"  # type: ignore[misc]


def test_graph_rejects_missing_dependency() -> None:
    step = TaskStep(
        id="step-a",
        task_id="task-1",
        tenant_id="tenant-a",
        user_id="user-a",
        dependencies={"missing"},
    )
    plan = TaskPlan(
        id="plan-1",
        task_id="task-1",
        tenant_id="tenant-a",
        user_id="user-a",
        steps=[step],
    )

    with pytest.raises(InvalidTaskGraph, match="missing"):
        TaskGraph(plan)


def test_graph_rejects_duplicate_step_ids() -> None:
    steps = [
        TaskStep("duplicate", "task-1", "tenant-a", "user-a"),
        TaskStep("duplicate", "task-1", "tenant-a", "user-a"),
    ]
    plan = TaskPlan("plan-1", "task-1", "tenant-a", "user-a", steps)

    with pytest.raises(InvalidTaskGraph, match="duplicate"):
        TaskGraph(plan)


def test_graph_rejects_self_dependency() -> None:
    step = TaskStep(
        "step-a", "task-1", "tenant-a", "user-a", dependencies={"step-a"}
    )
    plan = TaskPlan("plan-1", "task-1", "tenant-a", "user-a", [step])

    with pytest.raises(InvalidTaskGraph, match="itself"):
        TaskGraph(plan)


@pytest.mark.parametrize(
    ("field", "foreign_value"),
    (("task_id", "task-2"), ("tenant_id", "tenant-b"), ("user_id", "user-b")),
)
def test_graph_rejects_step_outside_plan_scope(
    field: str, foreign_value: str
) -> None:
    step = TaskStep(
        id="step-a",
        task_id=foreign_value if field == "task_id" else "task-1",
        tenant_id=foreign_value if field == "tenant_id" else "tenant-a",
        user_id=foreign_value if field == "user_id" else "user-a",
    )
    plan = TaskPlan("plan-1", "task-1", "tenant-a", "user-a", [step])

    with pytest.raises(InvalidTaskGraph, match=field):
        TaskGraph(plan)


def test_graph_rejects_dependency_cycles() -> None:
    steps = [
        TaskStep("step-a", "task-1", "tenant-a", "user-a", {"step-c"}),
        TaskStep("step-b", "task-1", "tenant-a", "user-a", {"step-a"}),
        TaskStep("step-c", "task-1", "tenant-a", "user-a", {"step-b"}),
    ]
    plan = TaskPlan("plan-1", "task-1", "tenant-a", "user-a", steps)

    with pytest.raises(InvalidTaskGraph, match="cycle"):
        TaskGraph(plan)


def test_ready_nodes_are_deterministic_and_respect_execution_state() -> None:
    steps = [
        TaskStep("step-c", "task-1", "tenant-a", "user-a", {"step-a"}),
        TaskStep("step-b", "task-1", "tenant-a", "user-a"),
        TaskStep("step-a", "task-1", "tenant-a", "user-a"),
        TaskStep("step-d", "task-1", "tenant-a", "user-a", {"step-b"}),
    ]
    graph = TaskGraph(TaskPlan("plan-1", "task-1", "tenant-a", "user-a", steps))

    assert tuple(step.id for step in graph.ready_nodes()) == ("step-a", "step-b")
    assert tuple(
        step.id
        for step in graph.ready_nodes(completed={"step-a"}, in_flight={"step-b"})
    ) == ("step-c",)
    assert tuple(
        step.id for step in graph.ready_nodes(completed={"step-a", "step-b"})
    ) == ("step-c", "step-d")


def test_ready_nodes_rejects_malformed_or_overlapping_execution_state() -> None:
    steps = [
        TaskStep("step-a", "task-1", "tenant-a", "user-a"),
        TaskStep("step-b", "task-1", "tenant-a", "user-a", {"step-a"}),
    ]
    graph = TaskGraph(TaskPlan("plan-1", "task-1", "tenant-a", "user-a", steps))

    for state_name in ("completed", "in_flight"):
        for malformed in ("step-a", ["step-a"], True, {""}, {1}):
            with pytest.raises(InvalidTaskGraph):
                graph.ready_nodes(**{state_name: malformed})  # type: ignore[arg-type]

    with pytest.raises(InvalidTaskGraph, match="overlap"):
        graph.ready_nodes(completed={"step-a"}, in_flight={"step-a"})


@pytest.mark.parametrize("state_name", ("completed", "in_flight"))
def test_ready_nodes_fail_closed_for_unknown_execution_state_ids(
    state_name: str,
) -> None:
    step = TaskStep("step-a", "task-1", "tenant-a", "user-a")
    graph = TaskGraph(
        TaskPlan("plan-1", "task-1", "tenant-a", "user-a", [step])
    )

    with pytest.raises(InvalidTaskGraph, match="unknown"):
        graph.ready_nodes(**{state_name: {"foreign-step"}})
