"""Asynchronous shadow consumer (Phase 8 §14, §18).

Drains the bounded local queue OFF the production sync path and feeds each
envelope into the existing Phase 7 ShadowRuntime (data only). The consumer never
blocks production; a shadow processing failure here is fail-recorded, never
propagated. Comparison is audit/metric only (no feedback loop).
"""

from __future__ import annotations

import time
from typing import Callable

from agent.platform_shadow import ShadowRuntime, ShadowTaskEnvelope

from .envelope import ProductionShadowEnvelope
from .metrics import ShadowHookMetrics
from .transport import ShadowTransport


class ShadowHookConsumer:
    """Bounded async worker: queue -> shadow runtime (non-blocking to production)."""

    __slots__ = ("_transport", "_shadow", "_metrics", "_clock")

    def __init__(
        self,
        *,
        transport: ShadowTransport,
        shadow: ShadowRuntime,
        metrics: ShadowHookMetrics,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._transport = transport
        self._shadow = shadow
        self._metrics = metrics
        self._clock = clock if clock is not None else time.monotonic

    def drain(self, limit: int = 64) -> int:
        """Process up to ``limit`` queued envelopes; record-only on any failure."""
        start = self._clock()
        processed = 0
        for envelope in self._transport.drain(limit):
            try:
                adapted = self._adapt(envelope)
                self._shadow.dispatch(adapted)  # data only; shadow is fail-record
                processed += 1
            except Exception:
                # §18: comparison/observability only; never propagate to production.
                self._metrics.increment("shadow_hook_errors")
        self._metrics.accumulate_latency(
            "shadow_processing_latency_ms", (self._clock() - start) * 1000.0
        )
        return processed

    @staticmethod
    def _adapt(env: ProductionShadowEnvelope) -> ShadowTaskEnvelope:
        pcd = "|".join(env.sanitized_context)[:256] or "n/a"
        return ShadowTaskEnvelope(
            shadow_id=env.trace_id,
            source_request_id=env.source_request_id,
            tenant_id=env.tenant_id,
            user_id=env.user_id,
            task_kind=env.request_kind,
            input_digest=env.input_digest,
            received_at=env.production_timestamp,
            sampling_reason="live-canary",
            production_context_digest=pcd,
            baseline_version=env.baseline_version,
        )


__all__ = ["ShadowHookConsumer"]