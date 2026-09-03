"""Fail-closed Capability Broker execution pipeline."""

from __future__ import annotations

from time import monotonic_ns
from typing import AbstractSet

from agent.platform_policy.permissions import PermissionGrant

from .audit import (
    AuditSink,
    CapabilityAuditEvent,
    NullAuditSink,
)
from .config import CapabilityBrokerConfig
from .context import TrustedCapabilityContext
from .dispatch import IntegrationDispatcher
from .errors import (
    CapabilityBrokerError,
    CapabilityDenied,
    CapabilityDisabled,
    InvalidCapabilityRequest,
    IntegrationUnavailable,
    SecretAccessDenied,
    SecretUnavailable,
    UnknownCapability,
    UpstreamAuthFailed,
    UpstreamError,
    UpstreamNotFound,
    UpstreamRateLimited,
)
from .models import (
    CapabilityOperationRequest,
    CapabilityResponse,
    CapabilityResult,
)
from .policy import require_capability
from .registry import CapabilityRegistry
from .sanitization import sanitize
from .secrets import ScopedSecretResolver, SecretBackend


_REASON_OK = "OK"
_REASON_BROKER_DISABLED = "CAPABILITY_DISABLED"
_REASON_INTEGRATION_DISABLED = "CAPABILITY_DISABLED"
_REASON_DENIED = "CAPABILITY_DENIED"
_REASON_UNKNOWN = "UNKNOWN_CAPABILITY"
_REASON_INVALID = "INVALID_ARGUMENT"
_REASON_SECRET = "SECRET_UNAVAILABLE"
_REASON_INTEGRATION = "INTEGRATION_UNAVAILABLE"
_REASON_UPSTREAM_AUTH = "UPSTREAM_AUTH_FAILED"
_REASON_UPSTREAM_NOT_FOUND = "UPSTREAM_NOT_FOUND"
_REASON_UPSTREAM_RATE_LIMITED = "UPSTREAM_RATE_LIMITED"
_REASON_UPSTREAM_ERROR = "UPSTREAM_ERROR"


class CapabilityBroker:
    """Execute registered integration reads under existing Hermes authority."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        config: CapabilityBrokerConfig,
        grants: AbstractSet[PermissionGrant],
        secret_backend: SecretBackend,
        testit_dispatcher: IntegrationDispatcher,
        audit_sink: AuditSink | None = None,
    ) -> None:
        if type(registry) is not CapabilityRegistry:
            raise TypeError("registry must be CapabilityRegistry")
        if not registry.frozen:
            raise ValueError("registry must be frozen before broker construction")
        if type(config) is not CapabilityBrokerConfig:
            raise TypeError("config must be CapabilityBrokerConfig")
        if not callable(secret_backend):
            raise TypeError("secret_backend must be callable")

        self._registry = registry
        self._config = config
        self._grants = frozenset(grants)
        self._secret_backend = secret_backend
        self._testit_dispatcher = testit_dispatcher
        self._audit_sink = audit_sink or NullAuditSink()

    def execute(
        self,
        request: CapabilityOperationRequest,
        *,
        context: TrustedCapabilityContext,
    ) -> CapabilityResponse:
        started = monotonic_ns()

        operation = (
            request.operation
            if type(request) is CapabilityOperationRequest
            else "[invalid]"
        )

        try:
            if type(request) is not CapabilityOperationRequest:
                raise InvalidCapabilityRequest(
                    "request must be CapabilityOperationRequest"
                )

            if type(context) is not TrustedCapabilityContext:
                raise InvalidCapabilityRequest(
                    "trusted context is required"
                )

            if not self._config.enabled:
                raise CapabilityDisabled("capability broker is disabled")

            definition = self._registry.resolve(request.operation)

            require_capability(
                definition,
                context,
                grants=self._grants,
            )

            if definition.integration != "testit":
                raise UnknownCapability(
                    "integration is not registered"
                )

            if not self._config.testit_enabled:
                raise CapabilityDisabled(
                    "TestIT capability is disabled"
                )

            resolver = ScopedSecretResolver(
                definition.required_secrets,
                backend=self._secret_backend,
            )
            secrets = resolver.resolve_required()

            raw = self._testit_dispatcher.execute(
                definition.action,
                request.arguments,
                secrets,
            )

            response = CapabilityResponse(
                result=CapabilityResult.SUCCESS,
                data=sanitize(raw),
                reason_code=_REASON_OK,
            )

            self._audit(
                context=context,
                operation=operation,
                decision="allow",
                result="success",
                reason_code=_REASON_OK,
                started=started,
            )
            return response

        except CapabilityDisabled:
            reason = (
                _REASON_BROKER_DISABLED
                if not self._config.enabled
                else _REASON_INTEGRATION_DISABLED
            )
            return self._failure(
                context=context,
                operation=operation,
                reason_code=reason,
                decision="deny",
                started=started,
            )

        except CapabilityDenied:
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_DENIED,
                decision="deny",
                started=started,
            )

        except UnknownCapability:
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_UNKNOWN,
                decision="deny",
                started=started,
            )

        except (InvalidCapabilityRequest, ValueError, TypeError):
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_INVALID,
                decision="deny",
                started=started,
            )

        except (SecretUnavailable, SecretAccessDenied):
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_SECRET,
                decision="deny",
                started=started,
            )

        except UpstreamAuthFailed:
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_UPSTREAM_AUTH,
                decision="error",
                started=started,
            )

        except UpstreamNotFound:
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_UPSTREAM_NOT_FOUND,
                decision="error",
                started=started,
            )

        except UpstreamRateLimited:
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_UPSTREAM_RATE_LIMITED,
                decision="error",
                started=started,
            )

        except UpstreamError:
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_UPSTREAM_ERROR,
                decision="error",
                started=started,
            )

        except IntegrationUnavailable:
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_INTEGRATION,
                decision="error",
                started=started,
            )

        except CapabilityBrokerError:
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_INTEGRATION,
                decision="error",
                started=started,
            )

        except Exception:
            # Never serialize raw unexpected exception text across the broker
            # boundary. This is intentionally fail-closed.
            return self._failure(
                context=context,
                operation=operation,
                reason_code=_REASON_INTEGRATION,
                decision="error",
                started=started,
            )

    def _failure(
        self,
        *,
        context: TrustedCapabilityContext,
        operation: str,
        reason_code: str,
        decision: str,
        started: int,
    ) -> CapabilityResponse:
        response = CapabilityResponse(
            result=(
                CapabilityResult.DENIED
                if decision == "deny"
                else CapabilityResult.ERROR
            ),
            data=None,
            reason_code=reason_code,
        )

        if type(context) is TrustedCapabilityContext:
            self._audit(
                context=context,
                operation=operation,
                decision=decision,
                result=response.result.value,
                reason_code=reason_code,
                started=started,
            )

        return response

    def _audit(
        self,
        *,
        context: TrustedCapabilityContext,
        operation: str,
        decision: str,
        result: str,
        reason_code: str,
        started: int,
    ) -> None:
        duration_ms = max(
            0,
            (monotonic_ns() - started) // 1_000_000,
        )

        event = CapabilityAuditEvent(
            # Authoritative correlation comes only from trusted context.
            request_id=context.request_id,
            operation=operation,
            tenant_id=context.principal.tenant_id,
            principal_id=context.principal.principal_id,
            surface=context.surface,
            decision=decision,
            result=result,
            reason_code=reason_code,
            duration_ms=duration_ms,
        )

        try:
            self._audit_sink.record(event)
        except Exception:
            # Audit persistence failure must never expose secrets or alter
            # execution response serialization in Phase 9.1.1.
            pass
