"""Exception hierarchy for the system-agent runtime layer.

All runtime-layer failures derive from a single base so callers can catch the
whole control-plane layer without reaching into the execution kernel.
"""


class SystemAgentError(Exception):
    """Base error for the system-agent runtime layer."""


class UnknownSystemAgent(SystemAgentError):
    """Raised when an operation references an agent id not registered in the layer."""


class CapabilityDeclarationError(SystemAgentError):
    """Raised on invalid or duplicate declarative capability metadata."""


class AgentHealthError(SystemAgentError):
    """Raised on invalid health observations or evaluation inputs."""


class ContextAssemblyError(SystemAgentError):
    """Raised when a context cannot be assembled safely (fail-closed)."""


class SystemAgentCoordinationError(SystemAgentError):
    """Raised on illegal coordination, routing, or messaging operations."""


class AgentRegistryDrift(SystemAgentError):
    """Raised when the sealed registry snapshot diverged (rebound/mutated registry)."""


class UnknownImplementation(SystemAgentError):
    """Raised when a definition carries an implementation id outside the canonical set."""