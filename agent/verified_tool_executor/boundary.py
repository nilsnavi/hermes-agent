"""System Boundary hook (Sprint 1.3.2 §25-§26 + Sprint 1.3.3 §4).

Sprint 1.3.2 prepared the injection point: the executor consults the
boundary for every execution BEFORE any adapter call. Sprint 1.3.3
replaces NoopSystemBoundary with the real System Boundary Layer
(``agent.system_boundary``), which adds the full pipeline:

    preflight(request, descriptor)          -> SystemPreflightPlan
    authorize(request, descriptor, preflight) -> BoundaryDecision
    verify_before_execute(request, descriptor, preflight) -> decision
    verify_after_execute(request, descriptor, result, preflight)

Backward compatibility: :class:`SystemBoundary` (Sprint 1.3.2 shape)
keeps ``authorize(request)``; the executor detects a Sprint 1.3.3
boundary by the presence of ``preflight`` and uses the full pipeline
when available, otherwise falls back to the legacy ``authorize`` call.
NoopSystemBoundary and DenySystemBoundary remain valid legacy
boundaries (rollback path).

Authority: the boundary is RESTRICTIVE — it may classify, raise risk,
require approval/validation/fresh preflight and BLOCK. It can never
reduce risk, grant capability authority, approve, create permissions
or bypass PolicyDecision / VerifiedToolExecutor (§2).
"""

from typing import Any, Dict, Optional, Protocol, runtime_checkable

from .models import BoundaryDecision, ExecutionRequest


@runtime_checkable
class SystemBoundary(Protocol):
    """§25 — Sprint 1.3.2 shape: ``authorize`` only.

    Answers "what host/system resources may this execution touch?" —
    a DIFFERENT question from the policy engine's "may this capability
    execute?". The concerns never merge.
    """

    def authorize(self, request: ExecutionRequest) -> BoundaryDecision:
        """Return ALLOW/DENY for one execution request."""
        ...

    def wrap_execution(self, *args: Any, **kwargs: Any) -> Any:
        """Optional execution wrapper (Sprint 1.3.3)."""
        ...


@runtime_checkable
class SystemBoundaryV2(Protocol):
    """§4 — Sprint 1.3.3 System Boundary Layer shape.

    Implemented by ``agent.system_boundary.SystemBoundaryLayer``.
    """

    BOUNDARY_VERSION: str

    def preflight(
        self,
        request: ExecutionRequest,
        descriptor: Any,
    ) -> Any:  # SystemPreflightPlan
        ...

    def authorize(
        self,
        request: ExecutionRequest,
        descriptor: Any,
        preflight: Any = None,  # SystemPreflightPlan | None
    ) -> BoundaryDecision:
        ...

    def verify_before_execute(
        self,
        request: ExecutionRequest,
        descriptor: Any,
        preflight: Any,  # SystemPreflightPlan | None
    ) -> BoundaryDecision:
        ...

    def verify_after_execute(
        self,
        request: ExecutionRequest,
        descriptor: Any,
        result: Any,
        preflight: Any,  # SystemPreflightPlan | None
    ) -> Any:
        ...


class NoopSystemBoundary:
    """§25 — the ONLY Sprint 1.3.2 boundary implementation.

    Always ALLOWs — it grants no new authority and enforces nothing.
    Its sole purpose is to prove the Sprint 1.3.3 insertion point:
    the executor consults the boundary on every execution and honours
    a DENY from any future implementation.
    """

    BOUNDARY_VERSION = "noop-v0"

    def authorize(self, request: ExecutionRequest) -> BoundaryDecision:
        return BoundaryDecision(
            verdict="ALLOW",
            reason_code=None,
            boundary_version=self.BOUNDARY_VERSION,
        )

    def wrap_execution(self, *args: Any, **kwargs: Any) -> Any:
        return None


class DenySystemBoundary:
    """Test/rollout helper — DENYs every execution.

    Used by the §48 boundary-hook tests to prove that a DENY from the
    Sprint 1.3.3 insertion point stops execution with zero adapter
    calls. NOT a production boundary.
    """

    BOUNDARY_VERSION = "deny-test-v0"

    def __init__(self, reason_code: str = "BOUNDARY_DENIED") -> None:
        self._reason = reason_code

    def authorize(self, request: ExecutionRequest) -> BoundaryDecision:
        return BoundaryDecision(
            verdict="DENY",
            reason_code=self._reason,
            boundary_version=self.BOUNDARY_VERSION,
        )

    def wrap_execution(self, *args: Any, **kwargs: Any) -> Any:
        return None


def is_v2_boundary(boundary: Any) -> bool:
    """True when the boundary implements the Sprint 1.3.3 pipeline
    (has preflight + verify_before_execute)."""
    return hasattr(boundary, "preflight") and \
        hasattr(boundary, "verify_before_execute")


__all__ = [
    "SystemBoundary",
    "SystemBoundaryV2",
    "NoopSystemBoundary",
    "DenySystemBoundary",
    "is_v2_boundary",
]
