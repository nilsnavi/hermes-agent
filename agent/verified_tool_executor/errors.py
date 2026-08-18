"""Canonical execution error taxonomy (Sprint 1.3.2 §24).

The executor NEVER lets a raw implementation exception escape the
public API — every failure is normalized into an
:class:`ExecutionResult` carrying ``error_class`` (short normalized
class) + ``error_code`` (one of the canonical codes below).

Canonical codes (§24):

    TOOL_NOT_REGISTERED      — tool name does not resolve from the
                               verified registry (no arbitrary names)
    TOOL_NOT_VERIFIED        — registered but descriptor.verified=False
    CAPABILITY_MISMATCH      — request.capability != registered
                               capability
    POLICY_NOT_ALLOWED       — policy verdict != ALLOW_V2 / version
                               mismatch (§45)
    INVALID_ARGUMENTS        — argument schema validation failed
                               (§8), incl. invalid timeout
    INVALID_TOOL_RESULT      — output schema validation failed (§9)
    TOOL_TIMEOUT             — descriptor/request deadline exceeded
    TOOL_CANCELLED           — cooperative cancellation
    TOOL_EXECUTION_ERROR     — adapter raised (normalized)
    DUPLICATE_ACTION         — exactly-once violation: same
                               (run_id, step_id, idempotency_key)
                               already executed / in flight
    UNKNOWN_EXECUTION_OUTCOME— side effect may have happened, outcome
                               unknown (restart recovery §32, timeout
                               on a non-read-only surface)
    BOUNDARY_REJECTED        — reserved for Sprint 1.3.3 System
                               Boundary Layer (§24)

Documented extensions beyond the §24 list (both are REJECTED/FAILED
fail-closed outcomes the brief itself mandates):

    TOOL_RISK_MISMATCH       — request expected side effect / risk
                               class incompatible with the descriptor
                               (§6 "risk compatible")
    TOOL_SIDE_EFFECT_VIOLATION — §34: descriptor says READ_ONLY but
                               the adapter reported WRITE/SYSTEM/
                               UNKNOWN → security violation, fail
                               closed, V2 tool route disabled
"""

from typing import Dict

# ── §24 canonical codes ────────────────────────────────────────────
TOOL_NOT_REGISTERED = "TOOL_NOT_REGISTERED"
TOOL_NOT_VERIFIED = "TOOL_NOT_VERIFIED"
CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
POLICY_NOT_ALLOWED = "POLICY_NOT_ALLOWED"
INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
INVALID_TOOL_RESULT = "INVALID_TOOL_RESULT"
TOOL_TIMEOUT = "TOOL_TIMEOUT"
TOOL_CANCELLED = "TOOL_CANCELLED"
TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
DUPLICATE_ACTION = "DUPLICATE_ACTION"
UNKNOWN_EXECUTION_OUTCOME = "UNKNOWN_EXECUTION_OUTCOME"
BOUNDARY_REJECTED = "BOUNDARY_REJECTED"

# ── documented extensions ──────────────────────────────────────────
TOOL_RISK_MISMATCH = "TOOL_RISK_MISMATCH"
TOOL_SIDE_EFFECT_VIOLATION = "TOOL_SIDE_EFFECT_VIOLATION"

#: The canonical code set (for fail-closed validation/tests).
EXECUTION_ERROR_CODES = frozenset({
    TOOL_NOT_REGISTERED,
    TOOL_NOT_VERIFIED,
    CAPABILITY_MISMATCH,
    POLICY_NOT_ALLOWED,
    INVALID_ARGUMENTS,
    INVALID_TOOL_RESULT,
    TOOL_TIMEOUT,
    TOOL_CANCELLED,
    TOOL_EXECUTION_ERROR,
    DUPLICATE_ACTION,
    UNKNOWN_EXECUTION_OUTCOME,
    BOUNDARY_REJECTED,
    TOOL_RISK_MISMATCH,
    TOOL_SIDE_EFFECT_VIOLATION,
})


class ExecutionErrorBase(Exception):
    """Base for contract-level executor errors."""


class VerifiedToolExecutionError(ExecutionErrorBase):
    """A contract violation raised by the executor internals.

    Always carries the canonical ``error_code``. Public API consumers
    receive ExecutionResult instead; this exception type exists for
    programmatic callers and internal guard failures.
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        return {"error_code": self.error_code, "message": self.message}


__all__ = [
    "TOOL_NOT_REGISTERED",
    "TOOL_NOT_VERIFIED",
    "CAPABILITY_MISMATCH",
    "POLICY_NOT_ALLOWED",
    "INVALID_ARGUMENTS",
    "INVALID_TOOL_RESULT",
    "TOOL_TIMEOUT",
    "TOOL_CANCELLED",
    "TOOL_EXECUTION_ERROR",
    "DUPLICATE_ACTION",
    "UNKNOWN_EXECUTION_OUTCOME",
    "BOUNDARY_REJECTED",
    "TOOL_RISK_MISMATCH",
    "TOOL_SIDE_EFFECT_VIOLATION",
    "EXECUTION_ERROR_CODES",
    "ExecutionErrorBase",
    "VerifiedToolExecutionError",
]
