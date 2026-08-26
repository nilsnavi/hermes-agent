"""Phase 8 live-hook exceptions (control plane, one-way, non-blocking)."""


class HookError(ValueError):
    """Base error for the production shadow hook (never reaches production)."""


class HookDisabledError(HookError):
    """Raised when the hook is disabled / kill-switched (no production impact)."""


class EnvelopeRejectedError(HookError):
    """A shadow envelope carried unsanitizable/invalid content and was dropped."""


class QueueUnavailableError(HookError):
    """Shadow transport unavailable / full -> drop shadow, continue production."""


__all__ = ["EnvelopeRejectedError", "HookDisabledError", "HookError", "QueueUnavailableError"]