"""The production shadow hook (Phase 8 §2, §3, §6).

Minimal one-way tap: sanitize/copy bounded metadata -> enqueue (non-blocking) ->
record success/drop. The hook itself contains NO planner/router/agent-runtime/
memory/comparison/policy/executor. All shadow processing stays in
``agent.platform_shadow``. There is NO API here that can apply/replace/override/
promote a shadow result back into production (PRODUCTION_RETURN_PATHS=0).
"""

from __future__ import annotations

import hashlib
import time
from enum import Enum
from typing import Callable, Mapping

from .envelope import (
    ProductionShadowEnvelope,
    assert_no_forbidden_content,
)
from .metrics import ShadowHookMetrics
from .modes import HookConfiguration
from .redaction import sanitize_context
from .transport import ShadowTransport


class EnqueueOutcome(Enum):
    ACCEPTED = "accepted"
    DROPPED = "dropped"
    UNAVAILABLE = "unavailable"


class ProductionShadowHook:
    """Non-blocking one-way hook; never touches production request/response."""

    __slots__ = ("_config", "_transport", "_metrics", "_clock", "_high_watermark")

    def __init__(
        self,
        *,
        config: HookConfiguration,
        transport: ShadowTransport,
        metrics: ShadowHookMetrics,
        clock: Callable[[], float] | None = None,
        high_watermark: int | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._metrics = metrics
        self._clock = clock if clock is not None else time.monotonic
        self._high_watermark = high_watermark

    def try_enqueue(
        self,
        *,
        source_request_id: str,
        tenant_id: str,
        user_id: str,
        request_kind: str,
        input_digest: str,
        production_timestamp: float,
        baseline_version: str,
        raw_context: Mapping[str, object],
        trace_id: str,
    ) -> EnqueueOutcome:
        """One-way, non-blocking enqueue. Never waits on shadow; never production-blocking.

        Returns ACCEPTED / DROPPED / UNAVAILABLE. In every non-ACCEPTED case the
        production path simply continues (shadow is dropped).
        """
        metrics = self._metrics
        metrics.increment("shadow_hook_received")
        start = self._clock()

        if not self._config.active():
            # Disabled / kill-switched -> return immediately, no tap, no enqueue.
            return EnqueueOutcome.UNAVAILABLE

        # §6 P0 close (review note 1): the ENTIRE body is guarded so ANY internal
        # exception (future real-backend transport, serialization, metric fault)
        # degrades to DROP_SHADOW and never propagates into the production path.
        try:
            return self._guarded_enqueue(
                source_request_id=source_request_id,
                tenant_id=tenant_id, user_id=user_id, request_kind=request_kind,
                input_digest=input_digest, production_timestamp=production_timestamp,
                baseline_version=baseline_version, raw_context=raw_context, trace_id=trace_id,
            )
        except Exception:
            metrics.increment("shadow_hook_errors")
            metrics.increment("shadow_hook_dropped")
            return EnqueueOutcome.DROPPED

    def _guarded_enqueue(self, **kw) -> EnqueueOutcome:
        metrics = self._metrics
        start = self._clock()
        source_request_id = str(kw["source_request_id"])
        tenant_id = str(kw["tenant_id"])
        user_id = str(kw["user_id"])
        request_kind = str(kw["request_kind"])
        input_digest = str(kw["input_digest"])
        production_timestamp = kw["production_timestamp"]
        baseline_version = str(kw["baseline_version"])
        raw_context = kw["raw_context"]
        trace_id = str(kw["trace_id"])

        # Deterministic bounded sampling (never a user-controlled field as authority).
        lane = int(hashlib.sha256(
            f"{request_kind}|{tenant_id}|{source_request_id}".encode("utf-8")
        ).hexdigest()[:8], 16) % 1000
        if lane >= self._config.sample_per_mille():
            metrics.increment("shadow_hook_dropped")
            return EnqueueOutcome.DROPPED

        metrics.increment("shadow_hook_sampled")
        try:
            context = sanitize_context(raw_context)
            envelope = ProductionShadowEnvelope(
                source_request_id=source_request_id,
                tenant_id=tenant_id,
                user_id=user_id,
                request_kind=request_kind,
                input_digest=input_digest,
                sanitized_context=context,
                production_timestamp=production_timestamp,
                baseline_version=baseline_version,
                trace_id=trace_id,
            )
            assert_no_forbidden_content(envelope)
        except (ValueError, TypeError):
            metrics.increment("shadow_hook_dropped_invalid")
            metrics.increment("shadow_hook_dropped")
            return EnqueueOutcome.DROPPED

        # Backpressure: over-budget / full -> drop shadow (never throttle production).
        if self._high_watermark is not None and self._transport.depth() >= self._high_watermark:
            metrics.increment("shadow_hook_dropped_over_budget")
            metrics.increment("shadow_hook_dropped")
            return EnqueueOutcome.DROPPED

        if not self._transport.try_enqueue(envelope):
            metrics.increment("shadow_hook_dropped_queue_full")
            metrics.increment("shadow_hook_dropped")
            return EnqueueOutcome.DROPPED

        metrics.increment("shadow_hook_enqueued")
        metrics.accumulate_latency("shadow_hook_latency_ms", (self._clock() - start) * 1000.0)
        return EnqueueOutcome.ACCEPTED


__all__ = ["EnqueueOutcome", "ProductionShadowHook"]