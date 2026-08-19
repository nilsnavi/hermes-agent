"""Sprint 1.3.11 — Limited Service Reload Policy (exceptions)."""


class ReloadPolicyError(Exception):
    pass


class PolicyDenied(ReloadPolicyError):
    pass


class NotAdmitted(PolicyDenied):
    pass


class ApprovalInvalid(PolicyDenied):
    pass


class BudgetExceeded(PolicyDenied):
    pass


class BreakerOpen(PolicyDenied):
    pass


class LockConflict(PolicyDenied):
    pass


class OperationDenied(PolicyDenied):
    pass