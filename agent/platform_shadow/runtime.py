"""Shadow runtime (Phase 7 §2, §18, §19, §20).

Composes the existing Phase 6 read-only vertical under a shadow lens. It NEVER
runs a second execution engine -- the only read site is still the injected
``ReadOnlyProvider`` reached post-admission inside the reused vertical. Shadow
output is DATA (``ShadowDecision``); it can never return, mutate or override a
production response, call a production executor, grant capabilities or change
scheduler/provider/gateway state.

Failure semantics (§18): UNKNOWN -> HUMAN_REVIEW candidate; TIMEOUT / BOUNDARY_
DENIED / MEMORY_DENIED / REGISTRY_DRIFT -> record only. No shadow failure can
affect or block the production request.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from agent.agent_integration.capabilities import ReadOnlyCapability
from agent.agent_integration.result import AgentObservation
from agent.agent_integration.vertical import ReadOnlyAgentVertical, VerticalResult

from .audit import ShadowAuditKind, ShadowAuditStore
from .claim_store import ClaimState, ShadowClaim, ShadowClaimStore
from .comparison import ComparisonEngine, ComparisonResult
from .exceptions import ShadowError, ShadowOverloaded, ShadowTimeout
from .guards import ShadowBudget
from .models import (
    ComparisonClass,
    ShadowDecision,
    ShadowTaskEnvelope,
)
from .observability import ShadowMetrics, ShadowTracer
from .sampling import ShadowSampler


def shadow_semantic_key(env: ShadowTaskEnvelope) -> str:
    """Durable shadow idempotency key (bound identity only; no secrets)."""
    from hashlib import sha256

    payload = "|".join(
        (env.tenant_id, env.user_id, env.task_kind, env.input_digest, env.baseline_version)
    )
    return sha256(payload.encode("utf-8")).hexdigest()


# Map the common task kinds to the bounded read-only capability they exercise.
def default_capability_for(task_kind: str) -> ReadOnlyCapability | None:
    mapping = {
        "monitoring": ReadOnlyCapability.READ_HEALTH,
        "research": ReadOnlyCapability.READ_TEXT_RESOURCE,
        "coding_shadow": ReadOnlyCapability.SEARCH_INDEX,
        "review": ReadOnlyCapability.READ_AUDIT_SUMMARY,
        "memory": ReadOnlyCapability.READ_MEMORY_CONTEXT,
    }
    return mapping.get(task_kind)


@dataclass(frozen=True, slots=True)
class ShadowRunOutcome:
    decision: ShadowDecision | None
    claimed: bool
    ran: bool
    reason: str


class ShadowRuntime:
    """Shadow runner over the Phase 6 read-only vertical (control plane, no prod effect)."""

    __slots__ = (
        "_sampler", "_budget", "_claims", "_vertical", "_audit", "_metrics",
        "_tracer", "_comparer", "_clock", "_capability_for", "_plan_fn",
        "_registry_digest", "_baseline_version", "_max_run_ms",
    )

    def __init__(
        self,
        *,
        sampler: ShadowSampler,
        budget: ShadowBudget,
        claims: ShadowClaimStore,
        vertical: ReadOnlyAgentVertical,
        audit: ShadowAuditStore,
        metrics: ShadowMetrics,
        tracer: ShadowTracer,
        clock: Callable[[], float] | None = None,
        capability_for: Callable[[str], ReadOnlyCapability | None] = default_capability_for,
        plan_fn: Callable[[ShadowTaskEnvelope], str] | None = None,
        registry_digest: str = "",
        baseline_version: str = "1.3.6",
        max_run_ms: int = 5000,
    ) -> None:
        self._sampler = sampler
        self._budget = budget
        self._claims = claims
        self._vertical = vertical
        self._audit = audit
        self._metrics = metrics
        self._tracer = tracer
        self._clock = clock if clock is not None else time.monotonic
        self._capability_for = capability_for
        self._plan_fn = plan_fn or default_plan
        self._registry_digest = registry_digest
        self._baseline_version = baseline_version
        self._max_run_ms = max_run_ms

    # -- top/lens -------------------------------------------------------------

    def dispatch(
        self,
        envelope: ShadowTaskEnvelope,
        production_decision: ShadowDecision | None = None,
    ) -> ShadowRunOutcome:
        """Run one shadow task copy. Never touches production; may return None (unsampled/skipped)."""

        metrics = self._metrics
        metrics.increment("shadow_tasks_received")
        self._trace(ShadowAuditKind.SHADOW_RECEIVED, envelope.shadow_id, envelope.shadow_id)

        sampled = self._sampler.sample(envelope)
        self._audit.append(shadow_id=envelope.shadow_id, kind=ShadowAuditKind.SHADOW_SAMPLED,
                           node_id=envelope.shadow_id, parent_id=envelope.shadow_id,
                           detail=f"mode={sampled.mode.value}")
        if not sampled.sampled:
            metrics.increment("shadow_tasks_sampled", 0)
            return ShadowRunOutcome(None, claimed=False, ran=False,
                                    reason=f"not sampled: {sampled.reason}")

        metrics.increment("shadow_tasks_sampled")
        try:
            self._budget.acquire()
        except ShadowOverloaded as exc:
            return ShadowRunOutcome(None, claimed=False, ran=False, reason=str(exc))
        try:
            return self._run_shadow(envelope, production_decision)
        except Exception:
            # §18/§19 close (review note 3): ANY shadow-internal error -- including
            # a full audit store or a claim backend fault -- is fail-recorded and
            # can never propagate into the production path.
            metrics.increment("shadow_tasks_failed")
            return ShadowRunOutcome(None, claimed=False, ran=False,
                                    reason="shadow internal error (production unaffected)")
        finally:
            self._budget.release()

    # -- internal -------------------------------------------------------------

    def _run_shadow(self, env: ShadowTaskEnvelope,
                    production: ShadowDecision | None) -> ShadowRunOutcome:
        metrics = self._metrics

        capability = self._capability_for(env.task_kind)
        if capability is None:
            metrics.increment("shadow_route_denied")
            return self._finish(env, None, claimed=False, ran=False,
                                reason="no capability mapped for task kind",
                                disposition="denied", comparison=ComparisonClass.SHADOW_DENIED)

        # Route once; capture the selected agent to satisfy the read-only chain.
        route = self._vertical._router.route(required_capability=capability)  # type: ignore[attr-defined]
        if route is None:
            metrics.increment("shadow_route_denied")
            return self._finish(env, None, claimed=False, ran=False,
                                reason="no admissible read-only agent",
                                disposition="denied", comparison=ComparisonClass.SHADOW_DENIED)
        agent_id = route.agent_id
        self._audit.append(shadow_id=env.shadow_id, kind=ShadowAuditKind.ROUTE_SELECTED,
                           node_id=agent_id, parent_id=env.shadow_id)
        self._trace(ShadowAuditKind.ROUTE_SELECTED, env.shadow_id, agent_id)

        # Durable run claim (Phase 7 §10). Fail-closed unknown -> do NOT run duplicate.
        claim = self._claims.claim(_key(env), "shadow")
        if claim.state is ClaimState.UNKNOWN:
            metrics.increment("shadow_tasks_unknown")
            return self._finish(env, None, claimed=False, ran=False,
                                reason="claim store unknown (fail-closed)",
                                disposition="unknown", comparison=ComparisonClass.SHADOW_UNKNOWN)
        if claim.state is ClaimState.LOST_DUPLICATE:
            metrics.increment("shadow_duplicate_runs")
            return self._finish(env, None, claimed=True, ran=False,
                                reason="duplicate shadow run (single winner)",
                                disposition="duplicate", comparison=ComparisonClass.NOT_COMPARABLE)

        plan_digest = self._plan_fn(env)
        self._audit.append(shadow_id=env.shadow_id, kind=ShadowAuditKind.PLAN_CREATED,
                           node_id=plan_digest, parent_id=env.shadow_id)
        self._trace(ShadowAuditKind.PLAN_CREATED, env.shadow_id, plan_digest)

        start = self._clock()
        try:
            result = self._vertical.execute_read_only(
                tenant_id=env.tenant_id,
                user_id=env.user_id,
                task_id=env.shadow_id,
                task_step_id=env.source_request_id,
                agent_id=agent_id,
                generation=1,
                agent_definition_version=1,
                registry_digest=self._registry_digest,
                input_text=f"shadow:{env.task_kind}",
                query_text="shadow read-only",
                capability=capability,
            )
        except ShadowTimeout:
            metrics.increment("shadow_tasks_failed")
            return self._finish(env, None, claimed=True, ran=False, reason="shadow timeout",
                                disposition="timeout", comparison=ComparisonClass.SHADOW_UNKNOWN)
        except Exception:
            # Phase 7 §18/§19: ANY shadow failure is recorded only and can never
            # break or propagate into the production path.
            metrics.increment("shadow_tasks_failed")
            return self._finish(env, None, claimed=True, ran=False,
                                reason="shadow runtime error (production unaffected)",
                                disposition="failed", comparison=ComparisonClass.SHADOW_UNKNOWN)

        decision = self._build_decision(env, capability.value, result, plan_digest, start,
                                        production, agent_id)
        self._claims.terminal(_key(env))
        self._audit.append(shadow_id=env.shadow_id, kind=ShadowAuditKind.SHADOW_COMPLETED,
                           node_id=env.shadow_id, parent_id=env.shadow_id,
                           detail=f"comparison={decision.comparison_class.value}")
        return ShadowRunOutcome(decision, claimed=True, ran=True, reason="completed")

    def _build_decision(self, env, capability_value, result: VerticalResult,
                        plan_digest, start, production, agent_id: str) -> ShadowDecision:
        metrics = self._metrics
        ae = result.audit_event
        observation = result.observation.summary if result.observation else ""
        disposition = result.state.value if result.state else "unknown"
        boundary = getattr(ae, "boundary_disposition", "") if ae else ""
        policy = getattr(ae, "policy_decision", "") if ae else ""
        memory_digest = getattr(ae, "memory_context_digest", "") if ae else ""
        duration_ms = (self._clock() - start) * 1000.0
        metrics.gauge("shadow_duration_ms", duration_ms)

        # Map outcome to shadow counters (§11) + a trace/audit chain.
        if result.outcome.value == "agent_completed":
            metrics.increment("shadow_tasks_completed")
            metrics.increment("shadow_agent_selected", labels={"agent_id": agent_id})
            self._trace(ShadowAuditKind.READ_OBSERVATION, env.shadow_id, "read:" + capability_value)
        elif result.outcome.value in ("agent_unknown", "agent_human_review"):
            metrics.increment("shadow_tasks_unknown")
            metrics.increment("shadow_human_review")
            self._trace(ShadowAuditKind.SUPERVISOR_DISPOSITION, env.shadow_id, disposition)
        elif result.outcome.value in ("policy_denied", "boundary_denied"):
            metrics.increment("shadow_boundary_denied")
            metrics.increment("shadow_tasks_failed")
            self._trace(ShadowAuditKind.BOUNDARY_DECIDED, env.shadow_id, boundary or "denied")
        else:
            metrics.increment("shadow_tasks_failed")

        comparison = ComparisonEngine.compare(production=production,
                                              shadow=ShadowDecision(
                                                  shadow_id=env.shadow_id,
                                                  task_id=env.shadow_id,
                                                  plan_digest=plan_digest,
                                                  selected_agent=agent_id,
                                                  agent_observation=observation,
                                                  supervisor_disposition=disposition,
                                                  confidence=0.8 if result.observation else 0.0,
                                                  policy_disposition=policy,
                                                  boundary_disposition=boundary,
                                                  memory_digest=memory_digest,
                                                  duration_ms=duration_ms,
                                                  comparison_class=ComparisonClass.NOT_COMPARABLE,
                                                  audit_id=""))
        if comparison.comparison_class is ComparisonClass.MATCH:
            metrics.increment("shadow_comparison_match")
        elif comparison.comparable:
            metrics.increment("shadow_comparison_mismatch")

        decision = ShadowDecision(
            shadow_id=env.shadow_id,
            task_id=env.shadow_id,
            plan_digest=plan_digest,
            selected_agent=agent_id,
            agent_observation=observation,
            supervisor_disposition=disposition,
            confidence=0.8 if result.observation else 0.0,
            policy_disposition=policy,
            boundary_disposition=boundary,
            memory_digest=memory_digest,
            duration_ms=duration_ms,
            comparison_class=comparison.comparison_class,
            audit_id=env.shadow_id,
        )
        metrics.increment("shadow_agent_selected", labels={"agent_id": agent_id})
        return decision

    def _finish(self, env, _obs, *, claimed, ran, reason, disposition,
                comparison) -> ShadowRunOutcome:
        self._audit.append(shadow_id=env.shadow_id, kind=ShadowAuditKind.SHADOW_COMPLETED,
                           node_id=env.shadow_id, parent_id=env.shadow_id, detail=reason)
        decision = None
        if comparison is not ComparisonClass.NOT_COMPARABLE:
            decision = ShadowDecision(
                shadow_id=env.shadow_id, task_id=env.shadow_id, plan_digest="",
                selected_agent="", agent_observation="", supervisor_disposition=disposition,
                confidence=0.0, policy_disposition="", boundary_disposition="",
                memory_digest="", duration_ms=0.0, comparison_class=comparison, audit_id="",
            )
        return ShadowRunOutcome(decision, claimed=claimed, ran=ran, reason=reason)

    def _trace(self, kind: ShadowAuditKind, shadow_id: str, node_id: str) -> None:
        before = self._tracer.kinds()
        self._tracer.record(kind.value, node_id, parent_id=shadow_id)
        del before


def _key(env: ShadowTaskEnvelope) -> str:
    return shadow_semantic_key(env)


def default_plan(env: ShadowTaskEnvelope) -> str:
    from hashlib import sha256

    return sha256(f"plan|{env.task_kind}|{env.input_digest}".encode("utf-8")).hexdigest()[:16]


__all__ = [
    "ShadowRunOutcome",
    "ShadowRuntime",
    "default_capability_for",
    "default_plan",
    "shadow_semantic_key",
]