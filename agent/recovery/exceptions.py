"""Recovery layer exceptions (Sprint 1.0.4)."""

from agent.execution.exceptions import ExecutionErrorBase


class RecoveryErrorBase(ExecutionErrorBase):
    """Base class for all recovery-layer errors."""


class NotResumable(RecoveryErrorBase):
    """A run cannot be resumed safely (wrong disposition / unknown outcome)."""


class RecoveryConflict(RecoveryErrorBase):
    """Concurrent recovery attempt on the same run (version guard)."""


__all__ = ["RecoveryErrorBase", "NotResumable", "RecoveryConflict"]
