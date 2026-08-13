"""Provider Registry V1 — public API (Sprint 0.4).

Compatibility layer over the existing Hermes provider subsystem:
- identity/metadata come from hermes_cli/providers.py (untouched)
- runtime state (health/auth/availability/circuit/eligibility) lives here
- nothing runs unless the feature flag is enabled; production behavior
  with the flag off is byte-identical to before.

Feature flag:  HERMES_PROVIDER_REGISTRY_V2  (default: false)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from .circuit import CircuitBreaker
from .classifier import Classification, ProviderErrorClassifier
from .domain import (
    AvailabilityReason,
    CircuitImpact,
    CircuitState,
    ProviderAuthStatus,
    ProviderDefinition,
    ProviderHealthStatus,
)
from .events import emit

FLAG_ENV = "HERMES_PROVIDER_REGISTRY_V2"

_TRUTHY = {"1", "true", "yes", "on", "y", "enable", "enabled"}


def flag_enabled(env: Optional[Dict[str, str]] = None) -> bool:
    """Feature flag: HERMES_PROVIDER_REGISTRY_V2, default false."""
    value = (env if env is not None else os.environ).get(FLAG_ENV, "")
    return value.strip().lower() in _TRUTHY


def set_flag(value: bool, env: Optional[Dict[str, str]] = None) -> None:
    """For tests / explicit mode switching. Never persists to disk."""
    target = env if env is not None else os.environ
    if value:
        target[FLAG_ENV] = "true"
    else:
        target.pop(FLAG_ENV, None)


class ProviderRegistry:
    """Thread-safe in-process provider state registry.

    Hermes runs the gateway as a single process (uvicorn worker); state is
    in-memory per process, protected by an RLock. Circuit state is
    intentionally memory-only (Sprint 0.4 §12: runtime health = memory,
    static definitions = config, telemetry = structured log events).
    """

    def __init__(
        self,
        classifier: Optional[ProviderErrorClassifier] = None,
        circuit: Optional[CircuitBreaker] = None,
    ) -> None:
        self._classifier = classifier or ProviderErrorClassifier()
        self._circuit = circuit or CircuitBreaker()
        self._defs: Dict[str, ProviderDefinition] = {}
        self._lock = threading.RLock()

    # ── registration ─────────────────────────────────────────────────────

    def register_provider(
        self,
        definition: ProviderDefinition,
        initial_health: ProviderHealthStatus = ProviderHealthStatus.UNKNOWN,
        initial_auth: ProviderAuthStatus = ProviderAuthStatus.UNKNOWN,
        initial_reason: AvailabilityReason = AvailabilityReason.NONE,
        initial_eligible: bool = False,
    ) -> None:
        with self._lock:
            definition.healthStatus = initial_health
            definition.authStatus = initial_auth
            definition.availabilityReason = initial_reason
            definition.routingEligible = initial_eligible
            self._defs[definition.id] = definition
        emit("provider.registered", provider=definition.id,
             status="registered", extra={"healthStatus": initial_health.value,
                                         "authStatus": initial_auth.value})

    def get_provider(self, provider_id: str) -> Optional[ProviderDefinition]:
        with self._lock:
            return self._defs.get(provider_id)

    def list_providers(self) -> List[ProviderDefinition]:
        with self._lock:
            return list(self._defs.values())

    # ── state transitions ────────────────────────────────────────────────

    def update_health(
        self,
        provider_id: str,
        health_status: Optional[ProviderHealthStatus] = None,
        auth_status: Optional[ProviderAuthStatus] = None,
        availability_reason: Optional[AvailabilityReason] = None,
        routing_eligible: Optional[bool] = None,
    ) -> bool:
        d = self.get_provider(provider_id)
        if d is None:
            return False
        with d.lock():
            if health_status is not None:
                d.healthStatus = health_status
            if auth_status is not None:
                d.authStatus = auth_status
            if availability_reason is not None:
                d.availabilityReason = availability_reason
            if routing_eligible is not None:
                d.routingEligible = routing_eligible
                self._emit_routing(d, provider_id)
        return True

    def record_success(
        self,
        provider_id: str,
        http_status: Optional[int] = None,
        duration_ms: Optional[float] = None,
    ) -> bool:
        d = self.get_provider(provider_id)
        if d is None:
            return False
        with d.lock():
            was_open = d.circuitState in (CircuitState.OPEN, CircuitState.HALF_OPEN)
            closed = self._circuit.record_success(d)
            d.lastSuccessAt = time.time()
            d.healthStatus = ProviderHealthStatus.HEALTHY
            d.availabilityReason = AvailabilityReason.NONE
            d.lastHttpStatus = http_status
            d.healthCheckedAt = time.time()
            if closed:
                d.routingEligible = True  # circuit closed → eligible again
            if closed and was_open:
                emit("provider.circuit.close", provider=provider_id, status="closed")
            emit("provider.health.success", provider=provider_id, status="healthy",
                 http_status=http_status, duration_ms=duration_ms)
            if d.routingEligible:
                emit("provider.routing.available", provider=provider_id, status="available",
                     extra={"routingEligible": True})
        return True

    def record_failure(
        self,
        provider_id: str,
        classification,
        http_status: Optional[int] = None,
        duration_ms: Optional[float] = None,
        source: str = "",
    ) -> bool:
        """Fold a classified failure into state.

        - permanent classes (auth/geo/waf/unsupported/quota): routing
          disabled directly, no circuit churn (Sprint §9)
        - transient classes: consecutive count + circuit breaker
        """
        d = self.get_provider(provider_id)
        if d is None:
            return False
        cls = classification
        with d.lock():
            d.lastFailureAt = time.time()
            d.lastErrorCode = cls.error_class.value
            d.lastHttpStatus = http_status
            d.healthCheckedAt = time.time()

            emit("provider.error.classified", provider=provider_id, status="failure",
                 http_status=http_status, error_class=cls.error_class.value,
                 duration_ms=duration_ms, extra={"detail": (cls.detail or "")[:120]})
            emit("provider.health.failure", provider=provider_id, status="failure",
                 http_status=http_status, error_class=cls.error_class.value, duration_ms=duration_ms)

            permanent = (not cls.retryable) or cls.circuit_impact.value == "HIGH"
            if permanent:
                # permanent class → routing disabled directly, no circuit churn
                d.healthStatus = ProviderHealthStatus.UNAVAILABLE
                d.routingEligible = False
                d.availabilityReason = cls.availability_reason or AvailabilityReason.AUTH
                d.consecutiveFailures += 1
                if cls.error_class.value == "AUTH_EXPIRED":
                    d.authStatus = ProviderAuthStatus.EXPIRED
                elif cls.error_class.value.startswith("AUTH_"):
                    d.authStatus = (
                        ProviderAuthStatus.MISSING
                        if cls.error_class.value == "AUTH_MISSING"
                        else ProviderAuthStatus.INVALID
                    )
                elif cls.error_class.value in ("GEO_BLOCKED", "WAF_BLOCKED"):
                    d.authStatus = ProviderAuthStatus.VALID  # platform block ≠ credential
                emit("provider.routing.disabled", provider=provider_id, status="disabled",
                     http_status=http_status, error_class=cls.error_class.value,
                     extra={"availabilityReason": d.availabilityReason.value})
                return True

            # transient → consecutive counter + circuit breaker
            d.consecutiveFailures += 1
            if d.healthStatus in (ProviderHealthStatus.HEALTHY, ProviderHealthStatus.UNKNOWN):
                d.healthStatus = ProviderHealthStatus.DEGRADED
            d.availabilityReason = cls.availability_reason
            opened = self._circuit.record_failure(d)
            if opened:
                emit("provider.circuit.open", provider=provider_id, status="open",
                     http_status=http_status, error_class=cls.error_class.value,
                     extra={"consecutiveFailures": d.consecutiveFailures})
                d.routingEligible = False
                emit("provider.routing.disabled", provider=provider_id, status="disabled",
                     extra={"circuitState": CircuitState.OPEN.value})
        return True

    # ── circuit breaker API ──────────────────────────────────────────────

    def open_circuit(self, provider_id: str) -> bool:
        d = self.get_provider(provider_id)
        if d is None:
            return False
        with d.lock():
            changed = self._circuit.open_now(d)
            d.routingEligible = False
            if changed:
                emit("provider.circuit.open", provider=provider_id, status="open")
        return changed

    def half_open_circuit(self, provider_id: str) -> bool:
        d = self.get_provider(provider_id)
        if d is None:
            return False
        with d.lock():
            if d.circuitState != CircuitState.HALF_OPEN:
                d.circuitState = CircuitState.HALF_OPEN
                emit("provider.circuit.half_open", provider=provider_id, status="half_open")
                return True
        return False

    def close_circuit(self, provider_id: str) -> bool:
        d = self.get_provider(provider_id)
        if d is None:
            return False
        with d.lock():
            was = d.circuitState
            closed = self._circuit.record_success(d)
            if closed and was != CircuitState.CLOSED:
                emit("provider.circuit.close", provider=provider_id, status="closed")
        return closed

    def circuit_state(self, provider_id: str) -> str:
        d = self.get_provider(provider_id)
        if d is None:
            return "UNKNOWN"
        with d.lock():
            return self._circuit.effective_state(d).value

    def update_models(self, provider_id: str, models: tuple) -> bool:
        d = self.get_provider(provider_id)
        if d is None:
            return False
        with d.lock():
            d.availableModels = tuple(models[:200])
            d.lastModelRefreshAt = time.time()
        return True

    # ── queries ──────────────────────────────────────────────────────────

    @staticmethod
    def _routing_blocked(d: ProviderDefinition) -> bool:
        return (
            not d.enabled
            or d.healthStatus in (ProviderHealthStatus.UNAVAILABLE, ProviderHealthStatus.DISABLED)
            or d.circuitState in (CircuitState.OPEN,)
        )

    @staticmethod
    def _routing_blocked_except_open(d: ProviderDefinition) -> bool:
        """Blocked for routing, ignoring the circuit state (half-open probe)."""
        return (
            not d.enabled
            or d.healthStatus in (ProviderHealthStatus.UNAVAILABLE, ProviderHealthStatus.DISABLED)
        )

    def is_routing_eligible(self, provider_id: str) -> bool:
        d = self.get_provider(provider_id)
        if d is None:
            return False
        with d.lock():
            self._circuit.maybe_half_open(d)  # lazy OPEN → HALF_OPEN
            if d.circuitState == CircuitState.HALF_OPEN:
                # half-open allows exactly one probe attempt
                return not self._routing_blocked_except_open(d)
            return d.routingEligible and not self._routing_blocked(d)

    def routing_eligibility_reason(self, provider_id: str) -> str:
        d = self.get_provider(provider_id)
        if d is None:
            return "NOT_REGISTERED"
        with d.lock():
            if not d.enabled:
                return "DISABLED"
            if d.healthStatus in (ProviderHealthStatus.UNAVAILABLE, ProviderHealthStatus.DISABLED):
                return d.availabilityReason.value
            if d.routingEligible is False:
                return d.availabilityReason.value
            if d.circuitState == CircuitState.OPEN:
                return "CIRCUIT_OPEN"
            return "ELIGIBLE" if d.routingEligible else d.availabilityReason.value

    def get_healthy_providers(self) -> List[Dict[str, Any]]:
        out = []
        for d in self.list_providers():
            with d.lock():
                if d.healthStatus == ProviderHealthStatus.HEALTHY:
                    out.append({"id": d.id, "defaultModel": d.defaultModel})
        return out

    def get_fallback_candidates(self) -> List[Dict[str, Any]]:
        """Eligible providers sorted by fallback priority (lower first),
        excluding the primary and explicitly broken ones."""
        primary_id = self._primary_id()
        candidates = []
        for d in self.list_providers():
            with d.lock():
                if d.id == primary_id:
                    continue
                if not self._routing_blocked(d) and d.routingEligible:
                    candidates.append({
                        "id": d.id,
                        "fallbackPriority": d.fallbackPriority if d.fallbackPriority is not None else 999,
                        "defaultModel": d.defaultModel,
                        "healthStatus": d.healthStatus.value,
                    })
        candidates.sort(key=lambda c: c["fallbackPriority"])
        return candidates

    def supports_model(self, provider_id: str, model: str) -> bool:
        d = self.get_provider(provider_id)
        if d is None:
            return False
        with d.lock():
            if not d.availableModels:
                # no fetched list → only the configured default is "known"
                return model == d.defaultModel
            return model in d.availableModels or model == d.defaultModel

    def supports_profile(self, provider_id: str, profile: str) -> bool:
        d = self.get_provider(provider_id)
        if d is None:
            return False
        with d.lock():
            return profile.upper() in d.supportedModelProfiles

    def get_provider_status(self, provider_id: str) -> Dict[str, Any]:
        d = self.get_provider(provider_id)
        if d is None:
            return {"id": provider_id, "registered": False}
        with d.lock():
            snap = d.snapshot()
            snap["circuitState"] = self._circuit.effective_state(d).value
            snap["routingEligibleEffective"] = self.is_routing_eligible(provider_id)
            snap["registered"] = True
            return snap

    def get_provider_statuses(self) -> List[Dict[str, Any]]:
        return [self.get_provider_status(d.id) for d in self.list_providers()]

    def registry_metrics(self) -> Dict[str, Any]:
        """No Prometheus stack exists in Hermes — expose an accessor dict
        for a future exporter (Sprint 0.4 §14)."""
        out = {}
        for s in self.get_provider_statuses():
            out[s["id"]] = {
                "health": s["healthStatus"],
                "circuit": s["circuitState"],
                "consecutiveFailures": s["consecutiveFailures"],
                "availabilityReason": s["availabilityReason"],
            }
        return out

    # ── internals ────────────────────────────────────────────────────────

    def _primary_id(self) -> str:
        with self._lock:
            for d in self._defs.values():
                if d.metadata.get("primary"):
                    return d.id
        return ""

    @staticmethod
    def _emit_routing(d: ProviderDefinition, provider_id: str) -> None:
        emit("provider.routing.available" if d.routingEligible else "provider.routing.disabled",
             provider=provider_id, status="available" if d.routingEligible else "disabled")


# ── lazy singleton (production use) ──────────────────────────────────────

_registry_singleton: Optional[ProviderRegistry] = None


def get_registry() -> Optional[ProviderRegistry]:
    """Return the process-wide registry — but ONLY if the feature flag is
    enabled. With the flag off this returns None and nothing executes."""
    global _registry_singleton
    if not flag_enabled():
        return None
    if _registry_singleton is None:
        _registry_singleton = ProviderRegistry()
    return _registry_singleton


def shutdown_registry() -> None:
    global _registry_singleton
    _registry_singleton = None


__all__ = [
    "FLAG_ENV", "flag_enabled", "set_flag",
    "ProviderRegistry", "get_registry", "shutdown_registry",
    # domain re-exports
    "ProviderDefinition", "ProviderHealthStatus", "ProviderAuthStatus",
    "CircuitState", "AvailabilityReason",
]