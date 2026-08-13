"""Integration lifecycle & health model (Sprint 0.7).

Foundation for Hermes 2.0 proactive event subsystem: a single, noise-free
lifecycle for all integrations — states, error classification, retry V2
(backoff+jitter), log deduplication, structured events, required/optional
policy — with an observability CLI.  Was designed to be opt-in: the gateway
may consult `integration_disabled()` without any other coupling.

Never touches DNS/network/firewall; never deletes configuration.
"""

from __future__ import annotations

from .classifier import classify_error, classify_exception, is_retryable
from .dedup import LogDedup
from .domain import ERROR_CLASSES, IntegrationState, IntegrationStatus
from .events import (
    health_failure,
    health_success,
    integration_disabled as emit_disabled,
    recovered,
    retry_scheduled,
    retry_suppressed,
)
from .registry import (
    DEFAULT_MANAGED,
    IntegrationRegistry,
    get_registry,
    integration_disabled,
)
from .retry import DEFAULT_BASE_SECONDS, next_delay, reset_on_success, should_retry

# Shared dedup per process (thread-safe).
_DEDUP = LogDedup()


def record_failure(integration: str, message: str, attempt: int) -> tuple:
    """Classify + dedup + emit + update registry state for a failure.

    Returns (suppressed: bool, error_class: str).  When ``suppressed`` the
    caller should keep its log line quiet (counter only); a periodic summary
    line is emitted automatically by the dedup.
    """
    ec = classify_error(message)
    suppressed = _DEDUP.should_suppress(integration, ec)
    if suppressed:
        if _DEDUP.should_summary(integration, ec):
            # §9 sparse summary: one line per window, not per attempt
            retry_suppressed(integration, ec, _DEDUP.count(integration, ec))
        return True, ec
    health_failure(integration, ec, attempt)
    try:
        # keep the observable registry truthful for live failures
        # (§15 CLI): last_failure / error_class / failure_count / attempt.
        from .registry import get_registry

        get_registry().mark_failure(integration, ec, attempt)
    except Exception:
        pass
    return False, ec

__all__ = [
    "DEFAULT_BASE_SECONDS", "DEFAULT_MANAGED", "ERROR_CLASSES",
    "IntegrationRegistry", "IntegrationState", "IntegrationStatus",
    "LogDedup", "classify_error", "classify_exception", "emit_disabled",
    "get_registry", "health_failure", "health_success", "integration_disabled",
    "is_retryable", "next_delay", "record_failure", "recovered",
    "reset_on_success", "retry_scheduled", "retry_suppressed", "should_retry",
]