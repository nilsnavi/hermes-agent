"""Immutable, bounded values exchanged across the agent lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .exceptions import AgentContractError

_MAX_TEXT_LENGTH = 65_536


def _require_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentContractError(f"{name} must be a non-empty string")
    _require_bounded_text(name, value)


def _require_bounded_text(name: str, value: str) -> None:
    if not isinstance(value, str):
        raise AgentContractError(f"{name} must be a string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise AgentContractError(
            f"{name} exceeds the {_MAX_TEXT_LENGTH}-character limit"
        )


def _require_bounded_strings(name: str, values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or len(values) > 256:
        raise AgentContractError(f"{name} must be a tuple with at most 256 items")
    for value in values:
        _require_bounded_text(name, value)


@dataclass(frozen=True, slots=True)
class AgentTask:
    """A bounded unit of work offered to an agent for analysis."""

    task_id: str
    input: str

    def __post_init__(self) -> None:
        _require_identifier("task_id", self.task_id)
        _require_bounded_text("input", self.input)


@dataclass(frozen=True, slots=True)
class AgentAnalysis:
    """Bounded analysis produced before an execution is attempted."""

    summary: str
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_bounded_text("summary", self.summary)
        _require_bounded_strings(
            "required_capabilities", self.required_capabilities
        )


@dataclass(frozen=True, slots=True)
class AgentExecutionContext:
    """Sanitized, bounded inputs approved for one agent run."""

    task_id: str
    step_id: str
    run_id: str
    input: str
    context: str = ""
    memory_references: tuple[str, ...] = ()
    memory_snippets: tuple[str, ...] = ()
    deadline: float | None = None
    cancellation_token: str | None = None
    permission_grant_reference: str = ""
    idempotency_key: str = ""
    approved_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("task_id", "step_id", "run_id"):
            _require_identifier(name, getattr(self, name))
        for name in ("input", "context"):
            _require_bounded_text(name, getattr(self, name))
        for name in (
            "memory_references",
            "memory_snippets",
            "approved_capabilities",
        ):
            _require_bounded_strings(name, getattr(self, name))
        if self.cancellation_token is not None:
            _require_bounded_text("cancellation_token", self.cancellation_token)
        for name in ("permission_grant_reference", "idempotency_key"):
            _require_bounded_text(name, getattr(self, name))
        if self.deadline is not None:
            if (
                isinstance(self.deadline, bool)
                or not isinstance(self.deadline, (int, float))
            ):
                raise AgentContractError("deadline must be a number or None")
            try:
                finite_deadline = isfinite(self.deadline)
            except OverflowError as exc:
                raise AgentContractError(
                    "deadline must be finite and nonnegative"
                ) from exc
            if not finite_deadline or self.deadline < 0:
                raise AgentContractError("deadline must be finite and nonnegative")

    def to_dict(self) -> dict[str, object]:
        """Serialize only the context's explicitly sanitized contract fields."""

        return {
            "task_id": self.task_id,
            "step_id": self.step_id,
            "run_id": self.run_id,
            "input": self.input,
            "context": self.context,
            "memory_references": self.memory_references,
            "memory_snippets": self.memory_snippets,
            "deadline": self.deadline,
            "cancellation_token": self.cancellation_token,
            "permission_grant_reference": self.permission_grant_reference,
            "idempotency_key": self.idempotency_key,
            "approved_capabilities": self.approved_capabilities,
        }


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Bounded output from a single agent run."""

    run_id: str
    output: str
    success: bool = True

    def __post_init__(self) -> None:
        _require_identifier("run_id", self.run_id)
        _require_bounded_text("output", self.output)
        if not isinstance(self.success, bool):
            raise AgentContractError("success must be a bool")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Independent validation verdict for an agent result."""

    valid: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.valid, bool):
            raise AgentContractError("valid must be a bool")
        _require_bounded_text("reason", self.reason)
