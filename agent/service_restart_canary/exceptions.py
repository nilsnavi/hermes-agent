"""Sprint 1.3.13 — single aux service restart canary (exceptions)."""
from __future__ import annotations


class RestartCanaryError(Exception):
    """Base for all service_restart_canary errors."""


class OperationDenied(RestartCanaryError):
    """Requested operation is denied (stop/start/generic/systemctl/gateway)."""


class NotRegistered(RestartCanaryError):
    """Service is not in the exact restart allowlist."""


class NotAdmitted(RestartCanaryError):
    """Service failed restart admission (profile/identity/graph/blast)."""


class ApprovalMissing(RestartCanaryError):
    """No valid single-use approval for the restart."""


class ApprovalExpired(RestartCanaryError):
    """Approval is bound to a drifted/expired plan."""


class BudgetExceeded(RestartCanaryError):
    """Restart budget exhausted (max_success/attempts)."""


class BreakerOpen(RestartCanaryError):
    """Restart circuit breaker is open."""


class LockConflict(RestartCanaryError):
    """Another transaction holds the per-service restart lock."""


class DuplicateRestart(RestartCanaryError):
    """Durable idempotency key already committed — no second restart."""


class CanaryDisabled(RestartCanaryError):
    """Canary is disabled (kill switch) — adapter calls denied."""


class RestartCommitFailed(RestartCanaryError):
    """Post-start stabilization health failed — do not COMMIT."""


class UnsupportedOperation(RestartCanaryError):
    """Operation not supported (STOP/START public, arbitrary signal)."""