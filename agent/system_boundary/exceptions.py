"""System Boundary Layer exceptions (Sprint 1.3.3 §49).

Fail closed: an unexpected exception inside any SBL component surfaces
as a BLOCK decision with SBL_INTERNAL_ERROR — an exception must NEVER
turn into a PASS.
"""


class SBLBaseError(Exception):
    """Base for SBL errors."""


class SBLInternalError(SBLBaseError):
    """An unexpected failure inside an SBL component.

    Always maps to BoundaryDecision(BLOCK, SBL_INTERNAL_ERROR).
    """


class SBLBlocked(SBLBaseError):
    """Execution was blocked by the System Boundary Layer.

    Carries the canonical reason code.
    """

    def __init__(self, reason_code: str, message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


class SBLRevalidateRequired(SBLBaseError):
    """Target/resource changed; execution requires a fresh preflight."""

    def __init__(self, reason_code: str = "PREFLIGHT_REQUIRED",
                 message: str = "") -> None:
        super().__init__(message or reason_code)
        self.reason_code = reason_code


class SBLBypassDetected(SBLBaseError):
    """An adapter invocation bypassed the SystemBoundary guard."""

    def __init__(self, message: str = "BOUNDARY_BYPASS_DETECTED") -> None:
        super().__init__(message)


class SBLPathUnresolved(SBLBaseError):
    """A target path could not be resolved (fail closed)."""


class SBLGraphUnavailable(SBLBaseError):
    """The service graph is unavailable / partial / corrupt."""


__all__ = [
    "SBLBaseError",
    "SBLInternalError",
    "SBLBlocked",
    "SBLRevalidateRequired",
    "SBLBypassDetected",
    "SBLPathUnresolved",
    "SBLGraphUnavailable",
]
