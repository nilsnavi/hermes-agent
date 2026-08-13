"""Provider-aware retry policy (Sprint 0.4 §8)."""

from __future__ import annotations

from dataclasses import dataclass

from .classifier import ProviderErrorClass


@dataclass(frozen=True)
class RetryPolicy:
    """Retry behavior for a single error class.

    max_retries: how many times the SAME request may be retried.
    backoff_base_s: exponential backoff base (seconds).
    backoff_max_s: cap for backoff.
    """

    retryable: bool
    max_retries: int = 0
    backoff_base_s: float = 1.0
    backoff_max_s: float = 60.0
    allow_model_switch: bool = False  # retry with a different compatible model

    def backoff(self, attempt: int) -> float:
        """Exponential backoff for attempt 0..n (attempt is zero-based)."""
        delay = self.backoff_base_s * (2 ** min(attempt, 6))
        return min(delay, self.backoff_max_s)


# Default policies per error class (§8).
DEFAULT_RETRY_POLICIES = {
    ProviderErrorClass.AUTH_INVALID: RetryPolicy(retryable=False),
    ProviderErrorClass.AUTH_EXPIRED: RetryPolicy(retryable=False),
    ProviderErrorClass.AUTH_MISSING: RetryPolicy(retryable=False),
    ProviderErrorClass.AUTH_UNSUPPORTED: RetryPolicy(retryable=False),
    ProviderErrorClass.GEO_BLOCKED: RetryPolicy(retryable=False),   # health cooldown instead
    ProviderErrorClass.WAF_BLOCKED: RetryPolicy(retryable=False),   # health cooldown instead
    ProviderErrorClass.MODEL_NOT_SUPPORTED: RetryPolicy(
        retryable=False, max_retries=1, allow_model_switch=True
    ),
    ProviderErrorClass.MODEL_NOT_FOUND: RetryPolicy(
        retryable=False, max_retries=1, allow_model_switch=True
    ),
    ProviderErrorClass.RATE_LIMITED: RetryPolicy(
        retryable=True, max_retries=3, backoff_base_s=2.0, backoff_max_s=60.0
    ),
    ProviderErrorClass.QUOTA_EXCEEDED: RetryPolicy(retryable=False),
    ProviderErrorClass.NETWORK_TIMEOUT: RetryPolicy(
        retryable=True, max_retries=2, backoff_base_s=1.0, backoff_max_s=15.0
    ),
    ProviderErrorClass.NETWORK_DNS: RetryPolicy(
        retryable=True, max_retries=2, backoff_base_s=1.0, backoff_max_s=15.0
    ),
    ProviderErrorClass.NETWORK_CONNECT: RetryPolicy(
        retryable=True, max_retries=2, backoff_base_s=1.0, backoff_max_s=15.0
    ),
    ProviderErrorClass.SERVER_ERROR: RetryPolicy(
        retryable=True, max_retries=2, backoff_base_s=2.0, backoff_max_s=30.0
    ),
    ProviderErrorClass.BAD_REQUEST: RetryPolicy(retryable=False),
    ProviderErrorClass.UNKNOWN: RetryPolicy(
        retryable=True, max_retries=1, backoff_base_s=1.0, backoff_max_s=10.0
    ),
}


class RetryPolicyProvider:
    """Resolves a RetryPolicy for a classified error (configurable)."""

    def __init__(self, overrides: dict | None = None) -> None:
        self._policies = dict(DEFAULT_RETRY_POLICIES)
        if overrides:
            for k, v in overrides.items():
                if k in self._policies:
                    self._policies[k] = v

    def policy_for(self, error_class: ProviderErrorClass) -> RetryPolicy:
        return self._policies.get(error_class, DEFAULT_RETRY_POLICIES[ProviderErrorClass.UNKNOWN])

    def max_retries_for(self, error_class: ProviderErrorClass) -> int:
        return self.policy_for(error_class).max_retries
