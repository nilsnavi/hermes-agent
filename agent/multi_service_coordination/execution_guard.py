"""Sprint 1.3.15 — P0 execution guard.

Even when every plan/approval/lock/budget/health gate is green, real execution
is DENIED with MULTI_SERVICE_EXECUTION_DISABLED.  adapter calls == 0.  This
file is the single hard line that keeps Sprint 1.3.15 simulation-only.
"""
from __future__ import annotations

MULTI_SERVICE_EXECUTION_DISABLED = "MULTI_SERVICE_EXECUTION_DISABLED"


def execution_disabled(*_args, **_kwargs) -> str:
    """Always returns the disabled reason.  No execution path exists."""
    return MULTI_SERVICE_EXECUTION_DISABLED


__all__ = ["MULTI_SERVICE_EXECUTION_DISABLED", "execution_disabled"]