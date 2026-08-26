"""The read-only vertical: first end-to-end Agent Platform contour (Phase 6 §2).

Composes the single controlled chain (NO second execution engine):

  Task/TaskStep + principal
    -> ReadOnlyRouter (runtime-owned, enabled, admissible, capability-matched)
    -> AgentRun isolation (bound identity + digests + idempotency)
    -> AgentContext assembly (Memory gateway Top-K, redacted/sanitized)
    -> Network policy (remote/network default DENIED)
    -> AgentCapabilityIntent -> PlatformPolicy -> SecurityBoundaryGate admission
    -> READ_ONLY disposition
    -> ReadOnlyProvider seam (the ONLY read site; reached only after admission
       AND an authorized runtime grant)
    -> AgentObservation
    -> Supervisor state disposition
    -> bounded audit event (append-only)

The vertical NEVER constructs a general execution engine: the only execution-adjacent
point is a narrow, injected ``ReadOnlyProvider`` which returns observations and is
reachable solely through an already-ADMITTED, grant-guarded read-only capability.
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from typing import Callable, Protocol

from agent.agent_security_boundary.admission import SecurityBoundaryGate
from agent.agent_security_boundary.intent import AgentCapabilityIntent
from agent.agent_security_boundary.status import (
    AdmissionOutcome,
    Disposition,
    SideEffectClass,
)

from .agent_run import AgentRun, AgentRunRegistry, RunIsolationError
from .audit_store import (
    AuditError,
    ExecutionAuditEvent,
    InMemoryAuditStore,
    PersistentAuditStore,
    build_audit_event,
)
from .capabilities import ReadOnlyCapability, access_class, is_read_only_allowed
from .context import AgentContextAssembler, AssembledAgentContext, MemoryPortal
from .error_taxonomy import AgentOutcome
from .gate_token import GrantDenied, RuntimeGrantSeal
from .metrics import MetricsRegistry
from .network_policy import NetworkReadOnlyPolicy
from .readonly_routing import (
    READONLY_AGENT_CAPABILITIES,
    ReadOnlyRouter,
    SealedRegistry,
)
from .result import AgentObservation
from .supervisor_state import AgentRunState, AgentRunStateMachine


class ReadOnlyProvider(Protocol):
    """The narrow, injected read-only source seam (NOT a general executor).

    Returned observations are DATA. It is only ever reached after the boundary
    admitted the capability AND the runtime grant authorized the call.
    """

    def read(
        self, *, capability: ReadOnlyCapability, context: AssembledAgentContext
    ) -> AgentObservation: ...


@dataclass(frozen=True, slots=True)
class VerticalResult:
    outcome: AgentOutcome
    state: AgentRunState
    run: AgentRun | None
    observation: AgentObservation | None = None
    audit_event: ExecutionAuditEvent | None = None
    reason: str = ""

    @property
    def succeeded(self) -> bool:
        return self.outcome is AgentOutcome.AGENT_COMPLETED


class ReadOnlyAgentVertical:
    """Composition root for the phase-6 read-only vertical."""

    __slots__ = (
        "_registry",
        "_gate",
        "_router",
        "_context",
        "_network",
        "_seal",
        "_provider",
        "_audit",
        "_metrics",
        "_runs",
        "_clock",
    )

    def __init__(
        self,
        *,
        registry: SealedRegistry,
        gate: SecurityBoundaryGate,
        router: ReadOnlyRouter,
        context: AgentContextAssembler,
        network_policy: NetworkReadOnlyPolicy,
        seal: RuntimeGrantSeal,
        provider: ReadOnlyProvider,
        audit: PersistentAuditStore,
        metrics: MetricsRegistry,
        runs: AgentRunRegistry,
        clock: Callable[[], float] | None = None,
    ) -> None:
        from time import time

        self._registry = registry
        self._gate = gate
        self._router = router
        self._context = context
        self._network = network_policy
        self._seal = seal
        self._provider = provider
        self._audit = audit
        self._metrics = metrics
        self._runs = runs
        self._clock = clock if clock is not None else time

    # -- public vertical -------------------------------------------------------

    def execute_read_only(
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
        query_text: str,
        capability: ReadOnlyCapability,
        supervisor_state: AgentRunState = AgentRunState.READY,
    ) -> VerticalResult:
        self._metrics.increment("agent_runs")

        # 1. Registry drift gate (fail-closed).
        try:
            self._registry.assert_registry_sealed()
        except Exception:
            self._metrics.increment("registry_drift")
            return VerticalResult(AgentOutcome.REGISTRY_DRIFT, AgentRunState.HUMAN_REVIEW, None,
                                  reason="registry snapshot drifted")

        # 2. Typed, bounded capability allowlist (no READ_ANYTHING).
        if type(capability) is not ReadOnlyCapability or not is_read_only_allowed(capability):
            return VerticalResult(AgentOutcome.POLICY_DENIED, AgentRunState.HUMAN_REVIEW, None,
                                  reason="capability is not a typed read-only token")

        # 3. Network policy: remote/network default DENIED unless certified.
        verdict = self._network.allows(capability)
        if not verdict.allowed:
            self._metrics.increment("boundary_denials")
            return VerticalResult(AgentOutcome.POLICY_DENIED, AgentRunState.HUMAN_REVIEW, None,
                                  reason=verdict.reason)

        # 3b. Declaration gate: the agent must DECLARE this read-only capability.
        #     Declaration is metadata (not a grant); final admission is still the
        #     SecurityBoundary below. Routing is only over declared capabilities.
        offered = READONLY_AGENT_CAPABILITIES.get(agent_id)
        if not offered or capability not in offered:
            return VerticalResult(AgentOutcome.POLICY_DENIED, AgentRunState.FAILED, None,
                                  reason=f"agent {agent_id!r} does not declare {capability.value}")

        # 4. AgentRun isolation + semantic idempotency.
        run = self._runs.create(
            tenant_id=tenant_id, user_id=user_id, task_id=task_id,
            task_step_id=task_step_id, agent_id=agent_id, generation=generation,
            agent_definition_version=agent_definition_version,
            registry_digest=registry_digest, input_text=input_text,
        )
        try:
            self._runs.assert_binds(
                run, tenant_id=tenant_id, user_id=user_id, task_id=task_id,
                agent_id=agent_id, generation=generation,
            )
        except RunIsolationError:
            self._metrics.increment("cross_tenant_denials")
            return VerticalResult(AgentOutcome.AGENT_FAILED_SAFE, AgentRunState.FAILED, run,
                                  reason="run reuse crosses an isolation boundary")
        if not self._runs.claim(run):
            self._metrics.increment("agent_run_duplicates")
            return VerticalResult(AgentOutcome.AGENT_COMPLETED, AgentRunState.COMPLETED, run,
                                  reason="duplicate: prior terminal/in-flight evidence exists (idempotency)")

        # 5. Agent context assembly via memory gateway Top-K (never "all memory").
        ctx = self._context.assemble(
            task_id=task_id, task_step_id=task_step_id, agent_id=agent_id,
            tenant_id=tenant_id, user_id=user_id, input_text=input_text,
            agent_definition_version=agent_definition_version,
            query_text=query_text, supervisor_state=supervisor_state,
        )

        # 6. Capability intent -> PlatformPolicy -> SecurityBoundary admission.
        intent = AgentCapabilityIntent(
            agent_id=agent_id, tenant_id=tenant_id, user_id=user_id,
            capability=capability.value,
            side_effect_class=SideEffectClass.READ_ONLY,
            task_id=task_id, task_step_id=task_step_id, agent_run_id=run.run_id,
        )
        decision = self._gate.admit(intent, caller_claims=())
        if not decision.allowed:
            self._metrics.increment("boundary_denials")
            if decision.disposition is Disposition.REGISTRY_DRIFT:
                return VerticalResult(AgentOutcome.REGISTRY_DRIFT, AgentRunState.HUMAN_REVIEW, run,
                                      reason=decision.reason)
            if decision.outcome is AdmissionOutcome.HUMAN_REVIEW:
                return VerticalResult(AgentOutcome.AGENT_HUMAN_REVIEW, AgentRunState.HUMAN_REVIEW, run,
                                      reason=decision.reason)
            outcome = (AgentOutcome.POLICY_DENIED if decision.policy_decision == "denied"
                       else AgentOutcome.BOUNDARY_DENIED)
            return VerticalResult(outcome, AgentRunState.FAILED, run, reason=decision.reason)

        # 7. Grant-guarded, admitted read-only provider seam (ONLY read site).
        state_machine = AgentRunStateMachine(AgentRunState.RUNNING)
        try:
            self._seal.guard(self._seal.current_grant())
            observation = self._provider.read(capability=capability, context=ctx)
        except GrantDenied:
            return VerticalResult(AgentOutcome.AGENT_FAILED_SAFE, AgentRunState.FAILED, run,
                                  reason="grant denied before read-only seam")
        except Exception as exc:
            terminal = AgentRunStateMachine(AgentRunState.RUNNING).transition(AgentRunState.UNKNOWN)
            return VerticalResult(AgentOutcome.AGENT_UNKNOWN, terminal.state, run,
                                  reason=f"read-only seam failed: {type(exc).__name__}")

        # 8. Supervisor disposition + terminal state (read-only, idempotent -> retryable).
        terminal_state = state_machine.transition(AgentRunState.COMPLETED).state

        # 9. Bounded audit event (append-only; data only).
        try:
            event = build_audit_event(
                task_id=task_id, task_step_id=task_step_id, agent_run_id=run.run_id,
                agent_id=agent_id, tenant_id=tenant_id, user_id=user_id,
                route_decision=agent_id,
                memory_context_digest=ctx.memory_context_digest,
                capability_intent=capability.value,
                policy_decision=decision.policy_decision,
                boundary_disposition=decision.disposition.value,
                execution_observation=observation.summary,
                supervisor_disposition=terminal_state.value,
                sequence=self._audit.count() + 1,
                timestamp=self._clock(),
            )
            self._audit.append(event)
        except AuditError as exc:
            return VerticalResult(AgentOutcome.AGENT_FAILED_SAFE, AgentRunState.FAILED, run,
                                  reason=f"audit write failed: {type(exc).__name__}")

        # 10. Terminal idempotency evidence + metrics.
        self._runs.record_terminal(run)
        self._metrics.increment("tasks_completed")
        return VerticalResult(AgentOutcome.AGENT_COMPLETED, terminal_state, run,
                              observation=observation, audit_event=event, reason="read-only completed")


_Allow = lambda: types.SimpleNamespace(allowed=True)  # noqa: E731


class _Deny:
    __slots__ = ("allowed", "reason")

    def __init__(self, reason: str) -> None:
        self.allowed = False
        self.reason = reason


# Phase 7 §9 close: NO generic allow-all. Only EXACT read-only enum values with a
# READ_ONLY side-effect class are admitted. Unknown capability / unknown
# side-effect class / NETWORK(read-only not in the enum) => DENY.
_READ_ONLY_CAPABILITY_VALUES = frozenset(c.value for c in ReadOnlyCapability)


def _deterministic_read_only(request) -> bool:
    """True only for an EXPLICIT read-only enum token with READ_ONLY semantics."""
    if type(request.side_effect_class) is not SideEffectClass:
        return False
    if request.side_effect_class is not SideEffectClass.READ_ONLY:
        return False
    return request.capability in _READ_ONLY_CAPABILITY_VALUES


class _DeterministicReadOnlyPolicy:
    def evaluate(self, request):  # request: AgentCapabilityIntent
        if not _deterministic_read_only(request):
            return _Deny("unknown / non-read-only capability => DENY")
        return _Allow()


class _ReadOnlyRouterSeam:
    def decide(self, request):
        if not _deterministic_read_only(request):
            return _Deny("router: only explicit read-only capabilities")
        return _Allow()


class _ReadOnlyBoundary:
    def preflight(self, request):
        if not _deterministic_read_only(request):
            return _Deny("boundary: not an explicit read-only capability")
        return _Allow()

    def authorize(self, request):
        if not _deterministic_read_only(request):
            return _Deny("boundary: not an explicit read-only capability")
        return _Allow()

    def verify_before_execute(self, request):
        if not _deterministic_read_only(request):
            return _Deny("boundary: not an explicit read-only capability")
        return _Allow()

    def verify_after_execute(self, request):
        if not _deterministic_read_only(request):
            return _Deny("boundary: not an explicit read-only capability")
        return _Allow()


class _ReadOnlyExecutor:
    def is_ready(self):
        return True

    def execute(self, request):
        return None  # seam; only reachable after policy/router/boundary allow read-only


class _ReadOnlySandboxAdapter:
    def run(self, payload):
        return "read-only-unused"  # never invoked for denied capabilities


def build_read_only_gate(*, registry: SealedRegistry | None = None) -> SecurityBoundaryGate:
    """Wire a SecurityBoundaryGate whose seams only admit explicit read-only.

    Phase 7 §9: replaces the Phase 6 allow-all stubs with a DETERMINISTIC policy.
    Only capabilities in the closed ``ReadOnlyCapability`` enum whose advertised
    side-effect class is ``READ_ONLY`` pass; unknown capability / unknown side-effect
    class / anything not on the enum => DENY (policy + router + boundary all agree).
    The gate's OWN fail-closed logic additionally hard-denies mutation/forbidden
    and misclassified side-effects. The caller may pass a runtime-owned registry so
    the gate also enforces agent membership.
    """
    return SecurityBoundaryGate(
        policy=_DeterministicReadOnlyPolicy(),
        capability_router=_ReadOnlyRouterSeam(),
        system_boundary=_ReadOnlyBoundary(),
        executor=_ReadOnlyExecutor(),
        sandbox=_ReadOnlySandboxAdapter(),
        registry=registry,
    )


__all__ = [
    "ReadOnlyAgentVertical",
    "ReadOnlyProvider",
    "VerticalResult",
    "build_read_only_gate",
]