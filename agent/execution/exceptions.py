"""Execution exception hierarchy (Sprint 1.0.2)."""


class ExecutionErrorBase(Exception):
    """Base class for all Execution Engine errors."""


class InvalidPlan(ExecutionErrorBase):
    """Raised when a plan cannot be built or is structurally invalid."""


class ToolNotAllowed(ExecutionErrorBase):
    """Raised when a tool is not registered (allowlist violation)."""

    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        super().__init__(f"tool not allowed: {tool_name}")


class ApprovalAlreadyDecided(ExecutionErrorBase):
    """Raised when an approval decision is attempted twice or on a decided
    request (duplicate approve/reject/expire)."""

    def __init__(self, approval_id: str, status: str):
        self.approval_id = approval_id
        self.status = status
        super().__init__(f"approval {approval_id} already decided ({status})")


class ApprovalExpired(ExecutionErrorBase):
    """Raised when deciding an approval that has passed its expires_at."""

    def __init__(self, approval_id: str):
        self.approval_id = approval_id
        super().__init__(f"approval {approval_id} expired")


class ConcurrentUpdateError(ExecutionErrorBase):
    """Raised when an optimistic-concurrency update hits a stale version.

    The row changed since it was read (two workers, double approval, late
    retry) — the caller must re-read and retry, never blind-overwrite.
    """

    def __init__(self, table: str, row_id: str):
        self.table = table
        self.row_id = row_id
        super().__init__(f"concurrent update conflict on {table}.{row_id}")
