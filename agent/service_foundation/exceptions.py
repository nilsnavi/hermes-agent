"""Sprint 1.3.9 — Controlled Service Mutation Foundation (exceptions)."""


class ServiceFoundationError(Exception):
    """Base. Never grants authority."""


class ExecutionDisabled(Exception):
    """Raised by execute() — service mutation execution is always DISABLED in 1.3.9."""


class SelfControlBlocked(Exception):
    """Self-control (gateway/runtime) prohibition triggered."""


class IdentityUnverified(Exception):
    """Service identity is not VERIFIED."""


class GraphUnhealthy(Exception):
    """Dependency graph is not HEALTHY/PARTIAL-safe."""
