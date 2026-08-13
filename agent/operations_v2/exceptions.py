"""Operations layer exceptions (Sprint 1.0.6.3)."""


class OperationsErrorBase(Exception):
    """Base class for all operations-layer errors."""


class RunNotFound(OperationsErrorBase):
    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"run not found: {run_id}")


class ApprovalNotFound(OperationsErrorBase):
    def __init__(self, approval_id: str):
        self.approval_id = approval_id
        super().__init__(f"approval not found: {approval_id}")


class UnauthorizedOperator(OperationsErrorBase):
    """Operator identity missing / unauthenticated / not allowed."""

    def __init__(self, reason: str = "operator is not authenticated"):
        self.reason = reason
        super().__init__(reason)


class ApprovalScopeMismatch(OperationsErrorBase):
    """Approval does not belong to the given run (run-scoped decisions)."""

    def __init__(self, approval_id: str, run_id: str):
        self.approval_id = approval_id
        self.run_id = run_id
        super().__init__(
            f"approval {approval_id} does not belong to run {run_id}"
        )


class ApprovalAlreadyDecidedError(OperationsErrorBase):
    """Approval is no longer PENDING (double decide / repeated expire)."""

    def __init__(self, approval_id: str, status: str):
        self.approval_id = approval_id
        self.status = status
        super().__init__(f"approval {approval_id} already decided ({status})")


class ApprovalExpiredError(OperationsErrorBase):
    """Approval passed its expires_at — decide as EXPIRED, never approve."""

    def __init__(self, approval_id: str):
        self.approval_id = approval_id
        super().__init__(f"approval {approval_id} expired")


class RunTerminalError(OperationsErrorBase):
    """Decision refused because the run reached a terminal state."""

    def __init__(self, run_id: str, status: str):
        self.run_id = run_id
        self.status = status
        super().__init__(f"run {run_id} is {status} — approval refused")


class StaleVersionError(OperationsErrorBase):
    """Expected approval version does not match the persisted one."""

    def __init__(self, approval_id: str, expected: int, actual: int):
        self.approval_id = approval_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"approval {approval_id} version mismatch: expected {expected}, "
            f"actual {actual} — reload required"
        )


class PolicyDeniedError(OperationsErrorBase):
    """Approval would permit an action outside the canary policy."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)
