"""Agent context assembly for the read-only vertical (Phase 6 §9, §10).

Assembles ONE bounded, data-only context for a read-only run from: task id,
task step id, agent definition metadata, tenant/user principal, memory Top-K
(via the Phase 3 memory gateway portal -- NEVER the raw backend), prior
read-only observations and supervisor state.

Excluded by construction: credentials, raw secrets, adapter references, the
executor object, authority/approval secrets, and raw system handles. Memory is
retrieved only through the bounded gateway pipeline (tenant -> scope ->
permission -> redaction -> injection sanitation -> Top-K), so an agent can
NEVER request "all memory". The assembled context is DATA, never authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent.platform_memory.memory_scopes import MemoryAccess
from agent.platform_memory.memory_security import (
    MemoryInjectionDetected,
    redact_secrets,
    sanitize_payload,
)
from agent.platform_memory.retrieval import ContextItem

from .agent_run import digest_of
from .supervisor_state import AgentRunState

_MAX_TOP_K = 8
_MAX_TEXT_LENGTH = 65_536
_MAX_SNIPPETS = 32


class MemoryPortal(Protocol):
    """Bounded retrieval portal (satisfied by the Phase 3 UnifiedMemoryGateway)."""

    def retrieve(
        self,
        *,
        access: MemoryAccess,
        query_text: str,
        top_k: int,
    ) -> tuple[ContextItem, ...]: ...


def _req(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise ValueError(f"{name} exceeds the {_MAX_TEXT_LENGTH}-character limit")
    return value


@dataclass(frozen=True, slots=True)
class AssembledAgentContext:
    """Immutable, bounded, authority-free context for one read-only run."""

    task_id: str
    task_step_id: str
    agent_id: str
    tenant_id: str
    user_id: str
    agent_definition_version: int
    registry_digest: str
    input_text: str
    memory_snippets: tuple[str, ...]
    memory_context_digest: str
    prior_observations: tuple[str, ...]
    supervisor_state: AgentRunState

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_step_id": self.task_step_id,
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "agent_definition_version": self.agent_definition_version,
            "registry_digest": self.registry_digest,
            "input_text": self.input_text,
            "memory_snippets": self.memory_snippets,
            "memory_context_digest": self.memory_context_digest,
            "prior_observations": self.prior_observations,
            "supervisor_state": self.supervisor_state.value,
            "authority_semantics": False,
        }


class AgentContextAssembler:
    """Sanitizing, bounded context builder over the memory portal."""

    __slots__ = ("_memory", "_registry_digest", "_max_top_k")

    def __init__(
        self,
        memory: MemoryPortal,
        *,
        registry_digest: str,
        max_top_k: int = _MAX_TOP_K,
    ) -> None:
        _req("registry_digest", registry_digest)
        if isinstance(max_top_k, bool) or not isinstance(max_top_k, int) or max_top_k < 1:
            raise ValueError("max_top_k must be a positive integer")
        self._memory = memory
        self._registry_digest = registry_digest
        self._max_top_k = max_top_k

    def assemble(
        self,
        *,
        task_id: str,
        task_step_id: str,
        agent_id: str,
        tenant_id: str,
        user_id: str,
        input_text: str,
        agent_definition_version: int,
        query_text: str,
        supervisor_state: AgentRunState = AgentRunState.READY,
        prior_observations: tuple[str, ...] = (),
    ) -> AssembledAgentContext:
        _req("task_id", task_id)
        _req("task_step_id", task_step_id)
        _req("agent_id", agent_id)
        _req("tenant_id", tenant_id)
        _req("input_text", input_text)
        _req("query_text", query_text)
        if (
            isinstance(agent_definition_version, bool)
            or not isinstance(agent_definition_version, int)
            or agent_definition_version < 1
        ):
            raise ValueError("agent_definition_version must be a positive integer")
        if type(supervisor_state) is not AgentRunState:
            raise ValueError("supervisor_state must be an exact AgentRunState value")

        access = MemoryAccess(tenant_id=tenant_id, user_id=user_id or "")
        # Bounded retrieval ONLY through the gateway portal (never "all memory").
        items = self._memory.retrieve(
            access=access, query_text=query_text, top_k=self._max_top_k
        )
        # Belt-and-braces re-sanitization at the LAST boundary before the agent:
        # redact inline secrets, drop injection-marked snippets (they are data,
        # never instructions), and reject any retrieval that over-supplies.
        sanitized: list[str] = []
        for item in items:
            text, _changed = redact_secrets(item.text)
            try:
                sanitize_payload((text,))
            except (MemoryInjectionDetected, ValueError):
                continue  # directive marker -> drop (data-only evidence, not passed on)
            sanitized.append(text)
        snippets = tuple(sanitized)
        if len(snippets) > _MAX_SNIPPETS:
            raise ValueError("memory retrieval exceeded the bounded snippet budget")
        memory_digest = digest_of("memory", *snippets) if snippets else "no-memory"

        obs = tuple(prior_observations)
        if len(obs) > 64:
            raise ValueError("prior_observations exceed the bounded budget")

        return AssembledAgentContext(
            task_id=task_id,
            task_step_id=task_step_id,
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id or "",
            agent_definition_version=agent_definition_version,
            registry_digest=self._registry_digest,
            input_text=input_text,
            memory_snippets=snippets,
            memory_context_digest=memory_digest,
            prior_observations=obs,
            supervisor_state=supervisor_state,
        )


__all__ = [
    "AgentContextAssembler",
    "AssembledAgentContext",
    "MemoryPortal",
]