"""Phase 7 shadow-runtime exceptions (control plane, no execution authority)."""


class ShadowError(ValueError):
    """Base error for the shadow runtime (never affects production)."""


class InvalidShadowEnvelope(ShadowError):
    """Raised when a shadow envelope carries forbidden or malformed content."""


class ShadowSamplingError(ShadowError):
    """Raised on an invalid sampling policy (never by normal flow)."""


class ShadowOverloaded(ShadowError):
    """Backpressure: shadow resource budget exhausted -> SKIP/DROP shadow."""


class ShadowClaimError(ShadowError):
    """Raised when a durable run claim cannot be resolved (fail-closed)."""


class ShadowTimeout(ShadowError):
    """A bounded shadow per-task/per-agent timeout elapsed (record only)."""


class ShadowIsolationError(ShadowError):
    """A forbidden production-side callable/reference entered the shadow runtime."""


__all__ = [
    "ShadowClaimError",
    "ShadowError",
    "ShadowIsolationError",
    "ShadowOverloaded",
    "ShadowSamplingError",
    "ShadowTimeout",
]