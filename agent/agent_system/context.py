"""Agent context assembly.

A pure builder that constructs a sanitized, bounded ``AgentExecutionContext``
(reused from the agent_runtime layer -- the model is not duplicated here) for a
single system agent run. Assembly is the place where the control plane checks
that the *approved* capability tokens placed into a context are a strict subset
of the target agent's *declared* capabilities (fail-closed): a context can never
carry a token the agent was not declared for.

An assembled context is DATA. ``AgentExecutionContext`` carries no executor, no
adapter and no authority, so the act of assembling a context cannot run anything.
Credentials, raw system prompts and executors are excluded by the model's bounded
contract and are never part of assembly input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent.agent_runtime.models import AgentExecutionContext

from .capabilities import CapabilitySurface, SystemCapability
from .exceptions import CapabilityDeclarationError, ContextAssemblyError, UnknownSystemAgent

_MAX_TEXT_LENGTH = 65_536


def _require_bounded_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextAssemblyError(f"{name} must be a non-empty string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise ContextAssemblyError(f"{name} exceeds the {_MAX_TEXT_LENGTH}-character limit")
    return value


@dataclass(frozen=True, slots=True)
class ContextSpec:
    """Bounded inputs a caller offers to context assembly."""

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


class ContextAssembler:
    """Sanitizing, fail-closed actor that builds one immutable agent context."""

    __slots__ = ("_clock",)

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        from time import time

        self._clock = clock if clock is not None else time

    def assemble(
        self,
        *,
        declared: CapabilitySurface,
        spec: ContextSpec,
        approved_capabilities: tuple[SystemCapability, ...] = (),
        agent_id: str | None = None,
    ) -> AgentExecutionContext:
        """Build a bounded context validating capability footprint (fail-closed).

        ``agent_id`` (when given) must match the declaration surface's owner.
        Every ``approved_capabilities`` token must be present in ``declared``;
        an undeclared token is rejected before any context is produced.
        """
        if type(declared) is not CapabilitySurface:
            raise ContextAssemblyError("declared must be an exact CapabilitySurface")
        if type(spec) is not ContextSpec:
            raise ContextAssemblyError("spec must be an exact ContextSpec value")
        if agent_id is not None:
            _require_bounded_text("agent_id", agent_id)
            if agent_id != declared.agent_id:
                raise UnknownSystemAgent(
                    f"agent_id {agent_id!r} does not match surface owner {declared.agent_id!r}"
                )
        if not isinstance(approved_capabilities, tuple):
            raise ContextAssemblyError("approved_capabilities must be a tuple")
        # Validate the capability footprint against the declared surface BEFORE
        # producing any context. Unknown/undeclared tokens cannot be smuggled in.
        approved_values: list[SystemCapability] = []
        for token in approved_capabilities:
            if type(token) is not SystemCapability:
                raise ContextAssemblyError(
                    "approved_capabilities must hold exact SystemCapability values"
                )
            if not declared.contains(token):
                raise ContextAssemblyError(
                    f"capability {token.value!r} is not declared for agent {declared.agent_id!r}"
                )
            approved_values.append(token)

        try:
            return AgentExecutionContext(
                task_id=spec.task_id,
                step_id=spec.step_id,
                run_id=spec.run_id,
                input=spec.input,
                context=spec.context,
                memory_references=spec.memory_references,
                memory_snippets=spec.memory_snippets,
                deadline=spec.deadline,
                cancellation_token=spec.cancellation_token,
                permission_grant_reference=spec.permission_grant_reference,
                idempotency_key=spec.idempotency_key,
                approved_capabilities=tuple(token.value for token in approved_values),
            )
        except CapabilityDeclarationError:
            raise
        except (TypeError, ValueError) as exc:  # model validation failures
            raise ContextAssemblyError(str(exc)) from exc


__all__ = ["ContextAssembler", "ContextSpec"]