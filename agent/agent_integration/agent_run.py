"""AgentRun isolation and semantic idempotency (Phase 6 §13, §26).

Every AgentRun is BOUND to its (tenant, user, task, step, agent, definition
generation) plus a set of digests (registry / context / memory). A run can be
reused only for the SAME bounded identity: cross-tenant, cross-user, cross-task,
cross-agent or cross-generation reuse is DENIED. A semantic idempotency key
(derived from task/step/agent/generation/input digest) means a duplicate must
NOT start a second identical work item when a prior terminal result exists.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from uuid import uuid4

from .supervisor_state import AgentRunState


class RunIsolationError(ValueError):
    """Raised on a run-reuse violation (e.g. cross-tenant binding)."""


def digest_of(*parts: str) -> str:
    """Deterministic SHA-256 digest label for a run binding (data only)."""
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _req(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunIsolationError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class AgentRunKey:
    """The bounding identity of one read-only agent run (data only)."""

    tenant_id: str
    user_id: str
    task_id: str
    task_step_id: str
    agent_id: str
    generation: int

    def __post_init__(self) -> None:
        for name in ("tenant_id", "user_id", "task_id", "task_step_id", "agent_id"):
            object.__setattr__(self, name, _req(name, getattr(self, name)))
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 1
        ):
            raise RunIsolationError("generation must be a positive integer")


@dataclass(frozen=True, slots=True)
class AgentRun:
    """An immutable, identity-bound read-only run handle."""

    run_id: str
    key: AgentRunKey
    agent_definition_version: int
    registry_digest: str
    input_digest: str
    context_digest: str = ""

    def __post_init__(self) -> None:
        _req("run_id", self.run_id)
        if type(self.key) is not AgentRunKey:
            raise RunIsolationError("key must be an exact AgentRunKey value")
        if (
            isinstance(self.agent_definition_version, bool)
            or not isinstance(self.agent_definition_version, int)
            or self.agent_definition_version < 1
        ):
            raise RunIsolationError("agent_definition_version must be a positive integer")
        _req("registry_digest", self.registry_digest)
        if not isinstance(self.input_digest, str) or not self.input_digest:
            raise RunIsolationError("input_digest must be a non-empty string")

    def idempotency_key(self) -> str:
        """Semantic key: tenant|user|task|step|agent|generation|input_digest."""
        k = self.key
        return digest_of(
            k.tenant_id, k.user_id, k.task_id, k.task_step_id, k.agent_id,
            str(k.generation), self.input_digest,
        )

    def binds_to(
        self,
        *,
        tenant_id: str,
        user_id: str,
        task_id: str,
        task_step_id: str,
        agent_id: str,
        generation: int,
    ) -> bool:
        """True only if the run is bound to EXACTLY this identity (isolation)."""
        k = self.key
        return (
            k.tenant_id == tenant_id
            and k.user_id == user_id
            and k.task_id == task_id
            and k.task_step_id == task_step_id
            and k.agent_id == agent_id
            and k.generation == generation
        )


class AgentRunRegistry:
    """Thread-safe ownership of identity-bound runs + terminal-idempotency map."""

    __slots__ = ("_runs", "_terminal_keys", "_claimed", "_lock")

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._terminal_keys: set[str] = set()
        self._claimed: set[str] = set()
        self._lock = threading.Lock()

    def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        task_id: str,
        task_step_id: str,
        agent_id: str,
        generation: int,
        agent_definition_version: int,
        registry_digest: str,
        input_text: str,
        context_digest: str = "",
    ) -> AgentRun:
        _req("tenant_id", tenant_id)
        _req("user_id", user_id)
        _req("task_id", task_id)
        _req("task_step_id", task_step_id)
        _req("agent_id", agent_id)
        _req("registry_digest", registry_digest)
        key = AgentRunKey(
            tenant_id=tenant_id, user_id=user_id, task_id=task_id,
            task_step_id=task_step_id, agent_id=agent_id, generation=generation,
        )
        input_digest = digest_of("input", input_text)
        run = AgentRun(
            run_id="run-" + uuid4().hex[:16],
            key=key,
            agent_definition_version=agent_definition_version,
            registry_digest=registry_digest,
            input_digest=input_digest,
            context_digest=context_digest,
        )
        with self._lock:
            self._runs[run.run_id] = run
        return run

    def assert_binds(self, run: AgentRun, *, tenant_id: str, user_id: str, task_id: str,
                     agent_id: str, generation: int) -> None:
        """DENY any reuse that crosses tenant/user/task/agent/generation."""
        if not isinstance(run, AgentRun):
            raise RunIsolationError("run must be an exact AgentRun value")
        if not run.binds_to(
            tenant_id=tenant_id, user_id=user_id, task_id=task_id,
            task_step_id=run.key.task_step_id, agent_id=agent_id, generation=generation,
        ):
            raise RunIsolationError("run reuse would cross a tenant/user/task/agent/generation boundary")

    def record_terminal(self, run: AgentRun) -> None:
        """Record that this run reached a terminal outcome (idempotency evidence)."""
        if type(run) is not AgentRun:
            raise RunIsolationError("run must be an exact AgentRun value")
        with self._lock:
            self._terminal_keys.add(run.idempotency_key())

    def claim(self, run: AgentRun) -> bool:
        """ATOMIC pre-execution claim: exactly ONE run per semantic identity may
        proceed; concurrent/repeat runs of the same identity are rejected.

        Returns True only for the first claimer of a not-already-terminal /
        not-already-claimed identity (duplicate execution = 0 under concurrency).
        """
        if type(run) is not AgentRun:
            raise RunIsolationError("run must be an exact AgentRun value")
        with self._lock:
            key = run.idempotency_key()
            if key in self._terminal_keys or key in self._claimed:
                return False
            self._claimed.add(key)
            return True

    def has_terminal_evidence(self, run: AgentRun) -> bool:
        if type(run) is not AgentRun:
            raise RunIsolationError("run must be an exact AgentRun value")
        with self._lock:
            return run.idempotency_key() in self._terminal_keys

    def is_duplicate(self, run: AgentRun) -> bool:
        """True iff a prior terminal result exists for this semantic identity."""
        return self.has_terminal_evidence(run)

    def run_count(self) -> int:
        with self._lock:
            return len(self._runs)


__all__ = [
    "AgentRun",
    "AgentRunKey",
    "AgentRunRegistry",
    "RunIsolationError",
    "digest_of",
]