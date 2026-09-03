"""Capability Broker error contracts.

Errors exposed across the broker boundary use bounded reason codes and never
serialize raw upstream exceptions, credentials, headers, or request bodies.
"""

from __future__ import annotations


class CapabilityBrokerError(RuntimeError):
    """Base broker failure."""


class InvalidCapabilityRequest(CapabilityBrokerError):
    """The operation request or its arguments are invalid."""


class InvalidTrustedContext(CapabilityBrokerError):
    """Trusted runtime provenance is absent or malformed."""


class CapabilityDisabled(CapabilityBrokerError):
    """The broker or integration capability is disabled."""


class CapabilityDenied(CapabilityBrokerError):
    """Policy or surface authorization denied the capability."""


class UnknownCapability(CapabilityBrokerError):
    """The requested broker operation is not registered."""


class RegistryFrozen(CapabilityBrokerError):
    """Mutation was attempted after registry freeze."""


class RegistryConfigurationError(CapabilityBrokerError):
    """A trusted registry definition is malformed."""


class SecretUnavailable(CapabilityBrokerError):
    """A required integration credential is unavailable."""


class SecretAccessDenied(CapabilityBrokerError):
    """A credential outside the capability-specific allowlist was requested."""


class IntegrationUnavailable(CapabilityBrokerError):
    """The integration could not be reached or completed safely."""


class UpstreamAuthFailed(CapabilityBrokerError):
    """The upstream integration rejected trusted credentials."""


class UpstreamNotFound(CapabilityBrokerError):
    """The requested upstream resource does not exist."""


class UpstreamRateLimited(CapabilityBrokerError):
    """The upstream integration rate-limited the request."""


class UpstreamError(CapabilityBrokerError):
    """The upstream integration returned another bounded failure."""
