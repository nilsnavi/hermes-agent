"""Isolated Shadow Worker orchestrator (Phase 8.3 §1, §2, §15).

The worker is a SEPARATE, independently executable process that holds ONLY the
consumer side of a one-way transport.  It never imports the gateway, never
holds a production request/response/executor, never has a reply path, and never
writes production memory.  It turns one ``ProductionShadowEnvelopeV1`` into one
read-only shadow run (reusing the Phase 7 ``ShadowRuntime`` which is itself a
single read side, not a second execution engine) and records it as DATA.

Failure semantics (§12): the worker may crash/timeout/fail; production has no
dependency on worker state.  The producer contract is out of this module's
scope (see ``transport.try_emit``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from agent.platform_shadow.claim_store import ClaimState, InMemoryClaimStore
from agent.platform_shadow.dispatcher import ShadowDispatcher
from agent.platform_shadow.models import (
    ComparisonClass,
    ShadowDecision,
    ShadowTaskEnvelope,
)
from agent.platform_shadow.runtime import ShadowRunOutcome, shadow_semantic_key

from .audit import WorkerAuditKind, WorkerAuditStore
from .config import WorkerConfig
from .envelope import (
    ENVELOPE_SCHEMA_VERSION,
    EnvelopeParseResult,
    ProductionShadowEnvelopeV1,
    parse_envelope,
)
from .exceptions import (
    EnvelopeValidationError,
    UnknownEnvelopeSchema,
    WorkerError,
    WorkerKillSwitchEngaged,
    WorkerRuntimeError,
)
from .health import WorkerHealth
from .lifecycle import WorkerLifecycle
from .metrics import WorkerMetrics
from .transport import OneWayConsumer


class WorkerStatus(Enum):
    """Outcome of processing one envelope (observability only)."""

    KILL_SWITCH = "kill_switch"
    INVALID = "invalid"
    UNKNOWN_SCHEMA = "unknown_schema"
    DUPLICATE = "duplicate"
    RAN = "ran"
    SKIPPED = "skipped"
    DENIED = "denied"
    UNKNOWN = "unknown"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    status: WorkerStatus
    event_id: str
    tenant_id: str
    reason: str
    shadow_decision: ShadowDecision | None = None


class ShadowRunner(Protocol):
    """The read-only shadow runner the worker drives (a ShadowDispatcher)."""

    def dispatch(
        self,
        envelope: ShadowTaskEnvelope,
        production_decision: ShadowDecision | None = None,
    ) -> ShadowRunOutcome: ...


class ShadowWorker:
    """Consumer-side orchestrator for the isolated shadow worker."""

    __slots__ = (
        "_config", "_transport", "_runner", "_metrics", "_audit", "_health",
        "_claims", "_envelope_count", "_processing",
    )

    def __init__(
        self,
        *,
        config: WorkerConfig,
        transport: OneWayConsumer,
        runner: ShadowRunner,
        metrics: WorkerMetrics | None = None,
        audit: WorkerAuditStore | None = None,
        health: WorkerHealth | None = None,
        claims: "InMemoryClaimStore | None" = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._runner = runner
        self._metrics = metrics if metrics is not None else WorkerMetrics()
        self._audit = audit if audit is not None else WorkerAuditStore()
        self._health = health if health is not None else WorkerHealth()
        # Durable single-winner idempotency at the WORKER boundary (§15): claim
        # first so concurrent duplicate envelopes never reach the read-only
        # vertical (duplicate_execution stays 0 even under race).
        self._claims = claims if claims is not None else InMemoryClaimStore()
        self._envelope_count = 0
        self._processing = 0

    # -- public entrypoints ---------------------------------------------------

    def config(self) -> WorkerConfig:
        return self._config

    def process_envelope(self, raw: bytes) -> WorkerOutcome:
        """Consume exactly one raw envelope; NEVER raises a production-affecting error."""
        self._envelope_count += 1
        self._metrics.increment("worker_envelopes_received")

        try:
            return self._process_envelope_inner(raw)
        except Exception as exc:  # noqa: BLE001  §12: any worker failure -> FAILED
            # A worker crash on ONE envelope must never take down the run loop or
            # the production path. Record it and continue.
            self._metrics.increment("worker_runs_failed")
            self._health.record_error(f"worker envelope failed: {exc}")
            return WorkerOutcome(WorkerStatus.FAILED, "", "", f"worker failure: {exc}")

    def _process_envelope_inner(self, raw: bytes) -> WorkerOutcome:
        parse: EnvelopeParseResult = parse_envelope(raw)

        # kill switch is evaluated BEFORE parsing/dispatching: worker refuses work.
        if self._config.kill_switch_engaged:
            self._metrics.increment("worker_envelopes_invalid")
            return WorkerOutcome(WorkerStatus.KILL_SWITCH, "", "", "kill switch engaged")

        if parse.status == "UNKNOWN_SCHEMA":
            self._record_invalid_phase()
            return WorkerOutcome(WorkerStatus.UNKNOWN_SCHEMA, "", "", parse.reason)
        if parse.status != "VALID" or parse.envelope is None:
            self._record_invalid_phase()
            return WorkerOutcome(WorkerStatus.INVALID, "", "", parse.reason)

        env = parse.envelope
        self._audit.append(event_id=env.event_id, tenant_id=env.tenant_id,
                           kind=WorkerAuditKind.ENVELOPE_RECEIVED)
        self._audit.append(event_id=env.event_id, tenant_id=env.tenant_id,
                           kind=WorkerAuditKind.ENVELOPE_VALIDATED,
                           detail=f"schema={env.schema_version}")

        # Sampling gate at the worker boundary: if config says OFF, we do not run.
        if self._config.sampling_mode == "off":
            return WorkerOutcome(WorkerStatus.SKIPPED, env.event_id, env.tenant_id,
                                 "sampling off")

        shadow_env = self._to_shadow_envelope(env)

        # Durable single-winner claim BEFORE the vertical (§15, §21 duplicate=0).
        # LOSER/UNKNOWN never touch the read-only vertical, so concurrent/duplicate
        # envelopes cannot double-execute and a failed claim never runs a duplicate.
        claim = self._claims.claim(shadow_semantic_key(shadow_env), "shadow_worker")
        if claim.state is ClaimState.LOST_DUPLICATE:
            self._metrics.increment("worker_envelopes_duplicate")
            self._audit.append(event_id=env.event_id, tenant_id=env.tenant_id,
                               kind=WorkerAuditKind.ENVELOPE_VALIDATED,
                               detail="claim lost (single winner)")
            return WorkerOutcome(WorkerStatus.DUPLICATE, env.event_id, env.tenant_id,
                                 "duplicate: single winner (worker claim)")
        if claim.state is ClaimState.UNKNOWN:
            self._metrics.increment("worker_runs_unknown")
            return WorkerOutcome(WorkerStatus.UNKNOWN, env.event_id, env.tenant_id,
                                 "claim store unknown (fail-closed)")

        outcome: ShadowRunOutcome
        started = time.monotonic()
        try:
            outcome = self._runner.dispatch(shadow_env)
        except (WorkerError, ValueError, TypeError):
            self._metrics.increment("worker_runs_failed")
            self._health.record_error("shadow dispatch raised (production unaffected)")
            return WorkerOutcome(WorkerStatus.FAILED, env.event_id, env.tenant_id,
                                 "shadow dispatch raised")
        finally:
            # single winner may replay its terminal outcome; mark terminal so a
            # later identical envelope is DUPLICATE (observability only).
            self._claims.terminal(shadow_semantic_key(shadow_env))
        duration_ms = (time.monotonic() - started) * 1000.0
        self._metrics.add_duration(duration_ms)

        return self._interpret(env, outcome)

    def run_once(self, timeout: float = 0.01) -> WorkerOutcome | None:
        """Pull one envelope from the one-way transport and process it."""
        raw = self._transport.recv(timeout=timeout)
        if raw is None:
            return None
        return self.process_envelope(raw)

    def run(self, *, until_empty: bool = False, max_iterations: int = 1_000_000) -> int:
        """Process loop (bounded). Returns number of envelopes processed."""
        processed = 0
        self._adjust_lifecycle(WorkerLifecycle.HEALTHY)
        try:
            while processed < max_iterations:
                outcome = self.run_once(timeout=0.01)
                if outcome is None:
                    if until_empty:
                        break
                    # small idle poll is bounded; worker may be killed externally
                    time.sleep(0.005)
                    continue
                processed += 1
                self._health.bump_processed(1)
        finally:
            self._adjust_lifecycle(WorkerLifecycle.STOPPING)
            self._adjust_lifecycle(WorkerLifecycle.STOPPED)
        return processed

    # -- internal -------------------------------------------------------------

    def _interpret(self, env: ProductionShadowEnvelopeV1,
                   outcome: ShadowRunOutcome) -> WorkerOutcome:
        base = WorkerOutcome(WorkerStatus.UNKNOWN, env.event_id, env.tenant_id, outcome.reason)
        decision = outcome.decision
        sid = outcome.claimed

        if not sid and not outcome.ran:
            if decision is None:
                self._metrics.increment("worker_envelopes_duplicate")
                self._audit.append(event_id=env.event_id, tenant_id=env.tenant_id,
                                   kind=WorkerAuditKind.ENVELOPE_VALIDATED,
                                   detail="duplicate/not-sampled single winner")
                return WorkerOutcome(WorkerStatus.DUPLICATE, env.event_id, env.tenant_id,
                                     outcome.reason, decision)
            cls = decision.comparison_class
            if cls is ComparisonClass.SHADOW_DENIED:
                self._metrics.increment("worker_boundary_denied")
                self._metrics.increment("worker_runs_unknown")
                return WorkerOutcome(WorkerStatus.DENIED, env.event_id, env.tenant_id,
                                     "shadow denied", decision)
            if cls is ComparisonClass.SHADOW_UNKNOWN:
                self._metrics.increment("worker_runs_unknown")
                return WorkerOutcome(WorkerStatus.UNKNOWN, env.event_id, env.tenant_id,
                                     "shadow unknown (fail-closed)", decision)
            return WorkerOutcome(WorkerStatus.DUPLICATE, env.event_id, env.tenant_id,
                                 "already claimed", decision)

        # claimed (single winner) and ran -> completed (or shadow-internal failure).
        self._metrics.increment("worker_runs_started")
        if outcome.ran:
            self._metrics.increment("worker_runs_completed")
        else:
            self._metrics.increment("worker_runs_failed")

        # Record the worker-level tail of the audit chain from the decision.
        self._append_tail_audit(env.event_id, env.tenant_id, decision)

        if outcome.ran:
            status = WorkerStatus.RAN
            self._audit.append(event_id=env.event_id, tenant_id=env.tenant_id,
                               kind=WorkerAuditKind.WORKER_COMPLETED)
        else:
            status = WorkerStatus.FAILED
            self._audit.append(event_id=env.event_id, tenant_id=env.tenant_id,
                               kind=WorkerAuditKind.WORKER_COMPLETED,
                               detail=f"reason={outcome.reason}")
        return WorkerOutcome(status, env.event_id, env.tenant_id, outcome.reason, decision)

    def _append_tail_audit(self, event_id: str, tenant_id: str,
                           decision: ShadowDecision | None) -> None:
        if decision is None:
            return
        if decision.selected_agent:
            self._audit.append(event_id=event_id, tenant_id=tenant_id,
                               kind=WorkerAuditKind.ROUTE_SELECTED,
                               detail=decision.selected_agent)
        if decision.memory_digest:
            self._audit.append(event_id=event_id, tenant_id=tenant_id,
                               kind=WorkerAuditKind.MEMORY_CONTEXT_BUILT,
                               detail=decision.memory_digest[:16])
        if decision.boundary_disposition:
            self._audit.append(event_id=event_id, tenant_id=tenant_id,
                               kind=WorkerAuditKind.BOUNDARY_DECIDED,
                               detail=decision.boundary_disposition)
        if decision.agent_observation:
            self._audit.append(event_id=event_id, tenant_id=tenant_id,
                               kind=WorkerAuditKind.OBSERVATION_CREATED,
                               detail="read_observation")
        if decision.supervisor_disposition:
            self._audit.append(event_id=event_id, tenant_id=tenant_id,
                               kind=WorkerAuditKind.SUPERVISOR_DISPOSITION,
                               detail=decision.supervisor_disposition)
        self._audit.append(event_id=event_id, tenant_id=tenant_id,
                           kind=WorkerAuditKind.COMPARISON_RECORDED,
                           detail=decision.comparison_class.value)

    def _to_shadow_envelope(self, env: ProductionShadowEnvelopeV1) -> ShadowTaskEnvelope:
        return ShadowTaskEnvelope(
            shadow_id=env.event_id,
            source_request_id=env.source_request_id,
            tenant_id=env.tenant_id,
            user_id=env.user_id,
            task_kind=env.request_kind,
            input_digest=env.input_digest,
            received_at=float(env.production_timestamp),
            sampling_reason="producer-tap",
            production_context_digest=env.input_digest,
            baseline_version=env.baseline_version,
        )

    def _record_invalid_phase(self) -> None:
        self._metrics.increment("worker_envelopes_invalid")

    def _adjust_lifecycle(self, value: WorkerLifecycle) -> None:
        try:
            self._health.set_lifecycle(value)
        except ValueError:  # ignore invalid transitions (informational only)
            pass

    def snapshot_metrics(self) -> dict[str, int]:
        self._metrics.set_queue_depth(self._transport.queue_depth())
        return self._metrics.snapshot()

    # Observability: informational only, never authority.
    @property
    def health(self) -> WorkerHealth:
        return self._health


__all__ = [
    "ShadowWorker",
    "ShadowRunner",
    "WorkerOutcome",
    "WorkerStatus",
]