"""Sprint 1.3.10 — single auxiliary service RELOAD canary (exceptions)."""


class ReloadCanaryError(Exception):
    pass


class ServiceOperationDenied(ReloadCanaryError):
    """restart/stop/start/kill/signal/daemon-reload are hard-denied."""


class ReloadIdentityDrift(ReloadCanaryError):
    pass


class ReloadGraphDrift(ReloadCanaryError):
    pass


class ReloadConfigInvalid(ReloadCanaryError):
    pass


class ReloadPreHealthFailure(ReloadCanaryError):
    pass


class ReloadApprovalInvalid(ReloadCanaryError):
    pass


class ReloadBudgetExceeded(ReloadCanaryError):
    pass


class ReloadCanaryDisabled(ReloadCanaryError):
    pass