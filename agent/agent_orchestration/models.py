from __future__ import annotations

from collections.abc import Set as SetABC
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, AbstractSet, Iterable

from .states import TaskStatus


class InvalidTaskTransition(ValueError):
    """Raised when a requested lifecycle transition is not legal."""


class StaleTaskVersion(RuntimeError):
    """Raised when a transition loses an optimistic concurrency race."""


_MAX_ID_LENGTH = 65_536


def _validate_identity(instance: object, fields: tuple[str, ...]) -> None:
    for name in fields:
        value = getattr(instance, name)
        if type(value) is not str or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        if len(value) > _MAX_ID_LENGTH:
            raise ValueError(f"{name} exceeds the {_MAX_ID_LENGTH}-character limit")


@dataclass(frozen=True)
class TaskTransition:
    from_status: TaskStatus
    to_status: TaskStatus
    version: int


_FORWARD_TRANSITIONS = {
    TaskStatus.CREATED: TaskStatus.PLANNING,
    TaskStatus.PLANNING: TaskStatus.EXECUTION,
    TaskStatus.EXECUTION: TaskStatus.VALIDATION,
    TaskStatus.VALIDATION: TaskStatus.COMPLETED,
}


@dataclass(frozen=True)
class TaskStep:
    id: str
    task_id: str
    tenant_id: str
    user_id: str
    dependencies: AbstractSet[str] = frozenset()

    def __post_init__(self) -> None:
        _validate_identity(self, ("id", "task_id", "tenant_id", "user_id"))
        if not isinstance(self.dependencies, SetABC) or isinstance(
            self.dependencies, (str, bytes)
        ):
            raise ValueError("dependencies must be a set-like collection of IDs")
        for dependency in self.dependencies:
            if type(dependency) is not str or not dependency.strip():
                raise ValueError("dependencies must contain non-empty string IDs")
            if len(dependency) > _MAX_ID_LENGTH:
                raise ValueError(
                    f"dependencies exceed the {_MAX_ID_LENGTH}-character limit"
                )
        object.__setattr__(self, "dependencies", frozenset(self.dependencies))


@dataclass(frozen=True)
class TaskPlan:
    id: str
    task_id: str
    tenant_id: str
    user_id: str
    steps: Iterable[TaskStep] = ()

    def __post_init__(self) -> None:
        _validate_identity(self, ("id", "task_id", "tenant_id", "user_id"))
        if isinstance(self.steps, (str, bytes)):
            raise ValueError("steps must be an iterable of TaskStep contracts")
        try:
            steps = tuple(self.steps)
        except TypeError as exc:
            raise ValueError("steps must be an iterable of TaskStep contracts") from exc
        if any(type(step) is not TaskStep for step in steps):
            raise ValueError("steps must contain only exact TaskStep contracts")
        object.__setattr__(self, "steps", steps)


@dataclass(frozen=True)
class _TaskLifecycle:
    status: TaskStatus
    version: int
    history: tuple[TaskTransition, ...]


class Task:
    """A new task whose lifecycle can change only through ``transition``."""

    def __init__(
        self,
        id: str,
        tenant_id: str,
        user_id: str,
        status: TaskStatus = TaskStatus.CREATED,
        context: dict[str, Any] | None = None,
        assigned_agents: Iterable[str] | None = None,
        history: Iterable[TaskTransition] | None = None,
        memory_links: Iterable[str] | None = None,
        version: int = 0,
    ) -> None:
        self.id = id
        self.tenant_id = tenant_id
        self.user_id = user_id
        _validate_identity(self, ("id", "tenant_id", "user_id"))

        try:
            initial_history = () if history is None else tuple(history)
        except TypeError as exc:
            raise ValueError("new task history must be empty") from exc
        if status is not TaskStatus.CREATED or type(version) is not int or version != 0:
            raise ValueError("new task must start in CREATED at version 0")
        if initial_history:
            raise ValueError("new task history must be empty")

        self.context = deepcopy({} if context is None else context)
        self.assigned_agents = deepcopy(
            [] if assigned_agents is None else list(assigned_agents)
        )
        self.memory_links = deepcopy(
            [] if memory_links is None else list(memory_links)
        )
        self._lifecycle = _TaskLifecycle(TaskStatus.CREATED, 0, ())

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"status", "version", "history"}:
            raise AttributeError(f"{name} is managed by transition()")
        if name in {"id", "tenant_id", "user_id"} and hasattr(self, name):
            raise AttributeError(f"{name} is immutable after initialization")
        if name == "_lifecycle" and hasattr(self, "_lifecycle"):
            raise AttributeError("task lifecycle is managed by transition()")
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        protected = {
            "id",
            "tenant_id",
            "user_id",
            "status",
            "version",
            "history",
            "_lifecycle",
        }
        if name in protected:
            raise AttributeError(f"{name} is immutable or managed by transition()")
        super().__delattr__(name)

    @property
    def status(self) -> TaskStatus:
        return self._lifecycle.status

    @property
    def version(self) -> int:
        return self._lifecycle.version

    @property
    def history(self) -> tuple[TaskTransition, ...]:
        return self._lifecycle.history

    def transition(self, to_status: TaskStatus, *, expected_version: int) -> None:
        if type(expected_version) is not int or expected_version != self.version:
            raise StaleTaskVersion(
                f"expected task version {expected_version!r}, found {self.version}"
            )
        legal_forward = _FORWARD_TRANSITIONS.get(self.status) is to_status
        legal_failure = self.status in _FORWARD_TRANSITIONS and to_status is TaskStatus.FAILED
        if not (legal_forward or legal_failure):
            target_name = to_status.name if isinstance(to_status, TaskStatus) else repr(to_status)
            raise InvalidTaskTransition(
                f"cannot transition from {self.status.name} to {target_name}"
            )
        next_version = self.version + 1
        transition = TaskTransition(self.status, to_status, next_version)
        next_lifecycle = _TaskLifecycle(
            to_status,
            next_version,
            (*self.history, transition),
        )
        object.__setattr__(self, "_lifecycle", next_lifecycle)
