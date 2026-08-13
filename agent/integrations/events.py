"""Integration lifecycle events (Sprint 0.7 §10).

Structured events, emitted through the shared provider_registry.events
bus.  Never carries credentials / Authorization / prompt content.
"""

from __future__ import annotations

from typing import Optional

from agent.provider_registry.events import emit


def _fields(integration: str, **kw):
    data = {"integration": integration}
    data.update(kw)
    return data


def health_success(integration: str, attempt: int = 0, duration_ms: Optional[int] = None) -> None:
    emit("integration.health.success", status="ok",
         extra=_fields(integration, attempt=attempt,
                       durationMs=duration_ms if duration_ms is not None else 0))


def health_failure(integration: str, error_class: str, attempt: int,
                   next_retry_at: Optional[float] = None) -> None:
    emit("integration.health.failure", status="error",
         extra=_fields(integration, errorClass=error_class, attempt=attempt,
                       nextRetryAt=next_retry_at))


def retry_scheduled(integration: str, error_class: str, attempt: int, delay_s: float) -> None:
    emit("integration.retry.scheduled", status="ok",
         extra=_fields(integration, errorClass=error_class, attempt=attempt,
                       nextRetryAt=round(delay_s, 1)))


def retry_suppressed(integration: str, error_class: str, count: int) -> None:
    emit("integration.retry.suppressed", status="ok",
         extra=_fields(integration, errorClass=error_class, suppressed=count))


def integration_disabled(integration: str, reason: str) -> None:
    emit("integration.disabled", status="ok",
         extra=_fields(integration, reason=reason))


def recovered(integration: str, attempt: int = 0) -> None:
    emit("integration.recovered", status="ok",
         extra=_fields(integration, attempt=attempt))