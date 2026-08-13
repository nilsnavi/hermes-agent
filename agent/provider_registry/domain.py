"""Provider Registry V1 — domain model.

Sprint 0.4: single source of truth for provider runtime state
(health, auth, availability, routing eligibility, circuit state).
Layered on top of the existing Hermes provider identity catalog
(hermes_cli/providers.py) — this module does NOT replace it.
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Enums ────────────────────────────────────────────────────────────────

class ProviderHealthStatus(enum.Enum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


class ProviderAuthStatus(enum.Enum):
    UNKNOWN = "UNKNOWN"
    VALID = "VALID"
    INVALID = "INVALID"
    EXPIRED = "EXPIRED"
    MISSING = "MISSING"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_REQUIRED = "NOT_REQUIRED"


class CircuitState(enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class AvailabilityReason(enum.Enum):
    NONE = "NONE"
    AUTH = "AUTH"
    GEO_BLOCKED = "GEO_BLOCKED"
    WAF_BLOCKED = "WAF_BLOCKED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    QUOTA = "QUOTA"
    RATE_LIMIT = "RATE_LIMIT"
    NETWORK = "NETWORK"
    CONFIGURATION = "CONFIGURATION"
    UNSUPPORTED_AUTH = "UNSUPPORTED_AUTH"
    MANUAL_REAUTH = "MANUAL_REAUTH"
    UNKNOWN = "UNKNOWN"


class CircuitImpact(enum.Enum):
    """How strongly an error affects the circuit / eligibility."""

    NONE = "NONE"        # no lasting impact
    LOW = "LOW"          # transient — count toward consecutive failures
    HIGH = "HIGH"        # permanent — disable routing directly


class ProviderModelProfile(enum.Enum):
    """Interface-level model profiles. Full Model Router = Sprint 0.5."""

    FAST = "FAST"
    BALANCED = "BALANCED"
    REASONING = "REASONING"
    CODING = "CODING"


# ── ProviderDefinition ───────────────────────────────────────────────────

@dataclass
class ProviderDefinition:
    """Static + runtime state for one provider.

    Static fields (id, displayName, enabled, authType, defaultModel,
    priority, fallbackPriority, metadata, probeSpec) are set at
    registration. Runtime fields are mutated by the registry under the
    per-provider lock.
    """

    # identity / static
    id: str
    displayName: str = ""
    enabled: bool = True
    authType: str = "api_key"          # api_key | oauth_device_code | oauth_external | external_process | virtual
    credentialConfigured: bool = False
    defaultModel: str = ""
    supportedModelProfiles: Tuple[str, ...] = ()
    priority: int = 100                # lower = higher priority for primary selection
    fallbackPriority: Optional[int] = None  # lower = tried first as fallback
    metadata: Dict[str, Any] = field(default_factory=dict)
    probeSpec: Optional[Dict[str, Any]] = None  # see health.py PROBE_SPECS

    # model support info (capped; not persisted)
    availableModels: Tuple[str, ...] = ()
    lastModelRefreshAt: Optional[float] = None

    # runtime health
    healthStatus: ProviderHealthStatus = ProviderHealthStatus.UNKNOWN
    authStatus: ProviderAuthStatus = ProviderAuthStatus.UNKNOWN
    availabilityReason: AvailabilityReason = AvailabilityReason.NONE
    routingEligible: bool = False

    # last observations
    lastSuccessAt: Optional[float] = None
    lastFailureAt: Optional[float] = None
    lastErrorCode: Optional[str] = None
    lastHttpStatus: Optional[int] = None

    # circuit
    consecutiveFailures: int = 0
    circuitState: CircuitState = CircuitState.CLOSED
    circuitOpenedAt: Optional[float] = None

    healthCheckedAt: Optional[float] = None

    # thread-safety (not serialized)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def lock(self) -> threading.RLock:
        return self._lock

    def snapshot(self) -> Dict[str, Any]:
        """Serializable snapshot WITHOUT secrets and without the lock."""
        return {
            "id": self.id,
            "displayName": self.displayName,
            "enabled": self.enabled,
            "authType": self.authType,
            "credentialConfigured": self.credentialConfigured,
            "defaultModel": self.defaultModel,
            "supportedModelProfiles": list(self.supportedModelProfiles),
            "priority": self.priority,
            "fallbackPriority": self.fallbackPriority,
            "healthStatus": self.healthStatus.value,
            "authStatus": self.authStatus.value,
            "availabilityReason": self.availabilityReason.value,
            "routingEligible": self.routingEligible,
            "lastSuccessAt": self.lastSuccessAt,
            "lastFailureAt": self.lastFailureAt,
            "lastErrorCode": self.lastErrorCode,
            "lastHttpStatus": self.lastHttpStatus,
            "consecutiveFailures": self.consecutiveFailures,
            "circuitState": self.circuitState.value,
            "circuitOpenedAt": self.circuitOpenedAt,
            "healthCheckedAt": self.healthCheckedAt,
            "availableModelsCount": len(self.availableModels),
            "lastModelRefreshAt": self.lastModelRefreshAt,
            "metadata": dict(self.metadata),
        }


# ── Registry events (structured observability) ───────────────────────────

#: Allowed structured event names (see events.py emit()).
REGISTRY_EVENTS = frozenset({
    "provider.registered",
    "provider.health.started",
    "provider.health.success",
    "provider.health.failure",
    "provider.error.classified",
    "provider.circuit.open",
    "provider.circuit.half_open",
    "provider.circuit.close",
    "provider.routing.disabled",
    "provider.routing.available",
    # Sprint 0.7 §9/§10: integration lifecycle events share the same
    # structured bus (see agent/integrations/events.py).
    "integration.health.success",
    "integration.health.failure",
    "integration.retry.scheduled",
    "integration.retry.suppressed",
    "integration.enabled",
    "integration.disabled",
    "integration.recovered",
})
