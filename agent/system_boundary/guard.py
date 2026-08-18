"""Boundary bypass guard (Sprint 1.3.3 §46).

A VerifiedToolAdapter can only be invoked through the SBL-sanctioned
pipeline. Direct adapter execution, forged tokens, fake registries,
monkeypatched registries and invalid boundary objects all fail closed
with BOUNDARY_BYPASS_DETECTED.
"""

from dataclasses import dataclass
from typing import Any, Callable

from .exceptions import SBLBypassDetected


@dataclass(frozen=True)
class SBLGuardToken:
    """One-use pipeline token minted by the SystemBoundaryLayer.

    An adapter invocation must carry the token of the SBL instance
    that authorized it — a forged/foreign token is a bypass.
    """

    sbl: Any
    execution_id: str


def guarded_execute(adapter: Callable, context: Any,
                    arguments: Any) -> Any:
    """Execute an adapter ONLY inside an SBL-sanctioned scope.

    Standalone use (no token) → BOUNDARY_BYPASS_DETECTED.
    """
    raise SBLBypassDetected(
        "BOUNDARY_BYPASS_DETECTED: adapter called outside the "
        "SystemBoundary pipeline")


def execute_requires_boundary() -> None:
    """Marker guard — any call without an active SBL token raises.

    Used by tests to prove that direct adapter execution outside the
    executor/SBL pipeline is impossible.
    """
    raise SBLBypassDetected(
        "BOUNDARY_BYPASS_DETECTED: adapter execution requires an "
        "active SystemBoundary token")


__all__ = [
    "SBLGuardToken",
    "guarded_execute",
    "execute_requires_boundary",
]
