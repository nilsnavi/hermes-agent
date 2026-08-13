"""Runtime exception hierarchy (Sprint 1.0.1)."""


class RuntimeErrorBase(Exception):
    """Base class for all Agent Runtime errors."""


class InvalidStateTransition(RuntimeErrorBase):
    """Raised when a run state change is not permitted by the state machine.

    Attributes:
        current: the run's status at the time of the attempt.
        target: the status the caller tried to enter.
    """

    def __init__(self, current, target):
        self.current = current
        self.target = target
        cur = getattr(current, "value", current)
        tgt = getattr(target, "value", target)
        super().__init__(f"invalid state transition: {cur} -> {tgt}")
