"""Intent Router exceptions (Sprint 1.1)."""


class IntentRouterError(Exception):
    """Base class for intent-router errors. Fail closed → LEGACY."""


class ClassificationError(IntentRouterError):
    """Classifier could not produce a classification."""


class RouterConfigurationError(IntentRouterError):
    """Bad flags / mode / policy configuration."""


class CapabilityUnknownError(IntentRouterError):
    """A referenced capability is not registered."""
