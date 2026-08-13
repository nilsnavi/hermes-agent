"""Integration lifecycle state model (Sprint 0.7 §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class IntegrationState(str, Enum):
    """Configured/enabled intent vs runtime health are separated.

    ``enabled`` (config intent) and ``health`` (runtime observation) live on
    IntegrationStatus; these are the *health* values.
    """

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    MISCONFIGURED = "MISCONFIGURED"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


# Error taxonomy (Sprint 0.7 §8) — a failure must never surface as a generic
# traceback; it is classified into one of these classes.
ERROR_CLASSES = (
    "DNS_FAILURE",
    "CONNECTION_REFUSED",
    "TIMEOUT",
    "AUTH_INVALID",
    "AUTH_EXPIRED",
    "HTTP_4XX",
    "HTTP_5XX",
    "RATE_LIMIT",
    "MISCONFIGURED",
    "DISABLED",
    "UNKNOWN",
)

NON_RETRYABLE_CLASSES = {
    "AUTH_INVALID",
    "AUTH_EXPIRED",
    "MISCONFIGURED",
    "DISABLED",
}


@dataclass
class IntegrationStatus:
    integration: str
    enabled: bool = True
    health: str = IntegrationState.UNKNOWN.value
    required: bool = False
    config_source: str = ""
    endpoint: str = ""          # display-only, no credentials
    auth_type: str = ""
    used_by: List[str] = field(default_factory=list)
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    failure_count: int = 0
    error_class: Optional[str] = None
    attempt: int = 0
    next_retry_at: Optional[float] = None
    retry_policy: str = "exponential+jitter"
    reason: str = ""

    @property
    def disabled(self) -> bool:
        return not self.enabled
