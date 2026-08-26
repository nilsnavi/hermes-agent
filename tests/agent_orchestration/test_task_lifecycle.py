from __future__ import annotations

import pytest

from agent.agent_orchestration import (
    InvalidTaskTransition,
    StaleTaskVersion,
    Task,
    TaskStatus,
)


import agent.agent_orchestration.models as lifecycle_models
from agent.agent_orchestration.models import TaskTransition


def test_task_status_has_exact_public_lifecycle() -> None:
    assert [status.name for status in TaskStatus] == [
        "CREATED",
        "PLANNING",
        "EXECUTION",
        "VALIDATION",
        "COMPLETED",
        "FAILED",
    ]


@pytest.mark.parametrize("field", ("id", "tenant_id", "user_id"))
def test_task_rejects_empty_identity(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        Task(
            id="   " if field == "id" else "task-1",
            tenant_id="   " if field == "tenant_id" else "tenant-a",
            user_id="   " if field == "user_id" else "user-a",
        )


def test_task_starts_created_with_scoped_empty_state() -> None:
    task = Task(id="task-1", tenant_id="tenant-a", user_id="user-a")

    assert task.id == "task-1"
    assert task.tenant_id == "tenant-a"
    assert task.user_id == "user-a"
    assert task.status is TaskStatus.CREATED
    assert task.context == {}
    assert task.assigned_agents == []
    assert task.history == ()
    assert task.memory_links == []
    assert task.version == 0


def test_task_rejects_forged_lifecycle_and_detaches_mutable_inputs() -> None:
    forged_transition = TaskTransition(
        TaskStatus.CREATED, TaskStatus.FAILED, version=1
    )
    for overrides in (
        {"status": TaskStatus.FAILED},
        {"version": 1},
        {"history": [forged_transition]},
    ):
        with pytest.raises(ValueError, match="new task"):
            Task(
                id="task-1",
                tenant_id="tenant-a",
                user_id="user-a",
                **overrides,
            )

    context = {"request": {"approved": True}}
    assigned_agents = ["agent-1"]
    memory_links = ["memory-1"]
    task = Task(
        id="task-1",
        tenant_id="tenant-a",
        user_id="user-a",
        context=context,
        assigned_agents=assigned_agents,
        memory_links=memory_links,
    )
    context["request"]["approved"] = False
    assigned_agents.append("agent-2")
    memory_links.append("memory-2")

    assert task.context == {"request": {"approved": True}}
    assert task.assigned_agents == ["agent-1"]
    assert task.memory_links == ["memory-1"]
    assert task.history == ()
    for field, replacement in (
        ("id", "replacement-task"),
        ("tenant_id", "tenant-b"),
        ("user_id", "user-b"),
        ("status", TaskStatus.FAILED),
        ("version", 99),
        ("history", (forged_transition,)),
    ):
        with pytest.raises(AttributeError):
            setattr(task, field, replacement)
    for field in ("id", "tenant_id", "user_id"):
        with pytest.raises(AttributeError, match="immutable"):
            delattr(task, field)


def test_transition_rejects_boolean_expected_version_without_mutation() -> None:
    task = Task(id="task-1", tenant_id="tenant-a", user_id="user-a")
    task.transition(TaskStatus.PLANNING, expected_version=0)
    initial_state = (task.status, task.version, task.history)

    with pytest.raises(StaleTaskVersion):
        task.transition(TaskStatus.EXECUTION, expected_version=True)

    assert (task.status, task.version, task.history) == initial_state


def test_transition_is_atomic_when_audit_record_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = Task(id="task-1", tenant_id="tenant-a", user_id="user-a")
    initial_state = (task.status, task.version, task.history)

    def fail_audit_record(*args: object, **kwargs: object) -> TaskTransition:
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(lifecycle_models, "TaskTransition", fail_audit_record)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        task.transition(TaskStatus.PLANNING, expected_version=0)

    assert (task.status, task.version, task.history) == initial_state
    with pytest.raises(AttributeError):
        task._lifecycle = object()  # type: ignore[assignment]


def test_forward_transitions_record_history_and_increment_version() -> None:
    task = Task(id="task-1", tenant_id="tenant-a", user_id="user-a")

    for expected_version, next_status in enumerate(
        (
            TaskStatus.PLANNING,
            TaskStatus.EXECUTION,
            TaskStatus.VALIDATION,
            TaskStatus.COMPLETED,
        )
    ):
        task.transition(next_status, expected_version=expected_version)

    assert task.status is TaskStatus.COMPLETED
    assert task.version == 4
    assert [(item.from_status, item.to_status) for item in task.history] == [
        (TaskStatus.CREATED, TaskStatus.PLANNING),
        (TaskStatus.PLANNING, TaskStatus.EXECUTION),
        (TaskStatus.EXECUTION, TaskStatus.VALIDATION),
        (TaskStatus.VALIDATION, TaskStatus.COMPLETED),
    ]
    assert [item.version for item in task.history] == [1, 2, 3, 4]


def test_transition_rejects_stale_expected_version_without_mutation() -> None:
    task = Task(id="task-1", tenant_id="tenant-a", user_id="user-a")

    with pytest.raises(StaleTaskVersion):
        task.transition(TaskStatus.PLANNING, expected_version=1)

    assert task.status is TaskStatus.CREATED
    assert task.version == 0
    assert task.history == ()


@pytest.mark.parametrize("forward_steps", range(4))
def test_failure_is_legal_from_every_nonterminal_state(forward_steps: int) -> None:
    task = Task(id="task-1", tenant_id="tenant-a", user_id="user-a")
    forward = (
        TaskStatus.PLANNING,
        TaskStatus.EXECUTION,
        TaskStatus.VALIDATION,
    )
    for next_status in forward[:forward_steps]:
        task.transition(next_status, expected_version=task.version)

    task.transition(TaskStatus.FAILED, expected_version=task.version)

    assert task.status is TaskStatus.FAILED
    assert task.history[-1].to_status is TaskStatus.FAILED


def test_transition_rejects_skipped_lifecycle_state_without_mutation() -> None:
    task = Task(id="task-1", tenant_id="tenant-a", user_id="user-a")

    with pytest.raises(InvalidTaskTransition):
        task.transition(TaskStatus.EXECUTION, expected_version=0)

    assert task.status is TaskStatus.CREATED
    assert task.version == 0
    assert task.history == ()


@pytest.mark.parametrize("terminal_status", (TaskStatus.COMPLETED, TaskStatus.FAILED))
def test_terminal_states_are_immutable(terminal_status: TaskStatus) -> None:
    task = Task(id="task-1", tenant_id="tenant-a", user_id="user-a")
    if terminal_status is TaskStatus.COMPLETED:
        for next_status in (
            TaskStatus.PLANNING,
            TaskStatus.EXECUTION,
            TaskStatus.VALIDATION,
            TaskStatus.COMPLETED,
        ):
            task.transition(next_status, expected_version=task.version)
    else:
        task.transition(TaskStatus.FAILED, expected_version=task.version)

    terminal_version = task.version
    with pytest.raises(InvalidTaskTransition):
        task.transition(TaskStatus.FAILED, expected_version=terminal_version)

    assert task.status is terminal_status
    assert task.version == terminal_version
