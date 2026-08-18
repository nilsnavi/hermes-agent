"""Execution contract data model (Sprint 1.3.2 §3-§5, §12, §26).

Pure data model — nothing here executes tools. Canonical objects:

- :class:`ExecutionRequest` (§3) — what the executor is asked to run:
  request/run/step ids, intent + subtype, capability + tool_name,
  policy evidence (version + decision id + verdict), arguments,
  timeout, idempotency key, expected side effect / risk class,
  optional operator context and bounded whitelisted metadata.
- :class:`ExecutionResult` (§4) — the canonical outcome: status,
  timing, output + output_hash, error_class/error_code, observed
  side effect, retryable, and the durable execution receipt.
- :class:`ExecutionContext` (§12) — immutable per-execution context
  handed to adapters (no raw prompt ever).
- :class:`ExecutionStatus` (§5) — the canonical status enum.
  ``UNKNOWN_OUTCOME`` is mandatory: ambiguous executions are never
  converted into FAILED when a side effect may already have happened.
- :class:`ExpectedSideEffect` / :class:`SideEffectReport` (§34) —
  expected vs observed side-effect vocabulary.
- :class:`BoundaryDecision` (§26) — Sprint 1.3.3 System Boundary
  result model (ALLOW/DENY + reason_code + boundary_version).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionStatus(Enum):
    """Canonical execution statuses (§5)."""

    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


#: Terminal statuses (a receipt in one of these is final).
TERMINAL_STATUSES = frozenset({
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMED_OUT,
    ExecutionStatus.CANCELLED,
    ExecutionStatus.REJECTED,
    ExecutionStatus.UNKNOWN_OUTCOME,
})


class ExpectedSideEffect(str, Enum):
    """What the REQUEST declares the tool may do (§3 / §6)."""

    NONE = "NONE"
    READ_ONLY = "READ_ONLY"
    REVERSIBLE_WRITE = "REVERSIBLE_WRITE"
    IRREVERSIBLE_WRITE = "IRREVERSIBLE_WRITE"
    SYSTEM_CHANGE = "SYSTEM_CHANGE"
    UNKNOWN = "UNKNOWN"


class SideEffectReport(str, Enum):
    """What the ADAPTER actually reports (§34)."""

    NONE = "NONE"
    READ_ONLY = "READ_ONLY"
    WRITE = "WRITE"
    SYSTEM = "SYSTEM"
    UNKNOWN = "UNKNOWN"


#: Report values compatible with a READ_ONLY descriptor (§34).
_READ_ONLY_COMPATIBLE_REPORTS = frozenset({
    SideEffectReport.NONE,
    SideEffectReport.READ_ONLY,
})


def side_effect_report_compatible_with_read_only(report: str) -> bool:
    """§34 — a READ_ONLY descriptor accepts only NONE/READ_ONLY."""
    try:
        value = SideEffectReport(report)
    except (TypeError, ValueError):
        return False
    return value in _READ_ONLY_COMPATIBLE_REPORTS


#: Bounded metadata allowlist (§3 — metadata is whitelisted only).
METADATA_ALLOWED_KEYS = frozenset({
    "goal",          # bounded safe request text (search fallback query)
    "channel",       # platform tag: telegram / api_server / feishu / max
    "source",        # LIVE / OFFLINE / TEST
    "sample_id",     # corpus case id (S1..S7, P1..P12, N1..N8)
})


def is_metadata_allowed(metadata: Dict[str, Any]) -> bool:
    """§3 — metadata is bounded/whitelisted; unknown keys rejected."""
    return set(metadata).issubset(METADATA_ALLOWED_KEYS)


@dataclass(frozen=True)
class ExecutionRequest:
    """§3 — canonical execution request."""

    request_id: str
    run_id: str
    step_id: str
    intent: str
    intent_subtype: str
    capability: str
    tool_name: str
    policy_version: str
    policy_decision_id: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 2000
    idempotency_key: str = ""
    expected_side_effect: str = ExpectedSideEffect.READ_ONLY.value
    expected_risk_class: str = "READ_ONLY"
    policy_verdict: str = "ALLOW_V2"  # canonical policy evidence (§45)
    operator_context: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "intent": self.intent,
            "intent_subtype": self.intent_subtype,
            "capability": self.capability,
            "tool_name": self.tool_name,
            "policy_version": self.policy_version,
            "policy_decision_id": self.policy_decision_id,
            "arguments": dict(self.arguments),
            "timeout_ms": self.timeout_ms,
            "idempotency_key": self.idempotency_key,
            "expected_side_effect": self.expected_side_effect,
            "expected_risk_class": self.expected_risk_class,
            "policy_verdict": self.policy_verdict,
            "operator_context": (
                dict(self.operator_context)
                if self.operator_context is not None else None
            ),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExecutionContext:
    """§12 — immutable context handed to adapters.

    No raw prompt, no auth, no credentials. ``deadline`` is the UTC
    datetime the execution must finish by; ``cancellation_token`` is a
    cooperative ``threading.Event`` — adapters may check it, the
    executor never pretends arbitrary execution was terminated.
    """

    request_id: str
    run_id: str
    step_id: str
    capability: str
    tool: str
    policy_version: str
    deadline: datetime
    cancellation_token: Any = None  # threading.Event (optional)
    #: Bounded (≤500 chars) safe goal text — search-query fallback for
    #: the operational search adapter. NOT the raw prompt; already
    #: router-validated + whitelisted metadata (§12, §24 invariants).
    goal: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "capability": self.capability,
            "tool": self.tool,
            "policy_version": self.policy_version,
            "deadline": self.deadline.isoformat(),
        }


@dataclass(frozen=True)
class ExecutionResult:
    """§4 — canonical execution result.

    ``error_class`` is a short normalized class name (e.g.
    SECURITY_VIOLATION / TIMEOUT / EXCEPTION); ``error_code`` is one of
    the canonical taxonomy codes (§24). ``execution_receipt`` is the
    durable receipt (also returned as a standalone object for §15
    consumers). No raw implementation exception ever escapes the
    executor — it is normalized into error_class/error_code.
    """

    execution_id: str
    request_id: str
    run_id: str
    step_id: str
    tool_name: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    output: Optional[Dict[str, Any]] = None
    output_hash: Optional[str] = None
    error_class: Optional[str] = None
    error_code: Optional[str] = None
    side_effect_observed: Optional[str] = None
    retryable: bool = False
    execution_receipt: Optional[Dict[str, Any]] = None
    duplicate_of: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status is ExecutionStatus.SUCCEEDED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat()
                if self.completed_at else None
            ),
            "duration_ms": self.duration_ms,
            "output": self.output,
            "output_hash": self.output_hash,
            "error_class": self.error_class,
            "error_code": self.error_code,
            "side_effect_observed": self.side_effect_observed,
            "retryable": self.retryable,
            "execution_receipt": self.execution_receipt,
            "duplicate_of": self.duplicate_of,
        }


@dataclass(frozen=True)
class BoundaryDecision:
    """§26 — Sprint 1.3.3 System Boundary result model.

    Prepared NOW as the interface; Sprint 1.3.2 only ever receives
    ALLOW from the NoopSystemBoundary (which grants no new authority).
    """

    verdict: str  # "ALLOW" | "DENY"
    reason_code: Optional[str] = None
    boundary_version: str = "noop-v0"

    @property
    def allow(self) -> bool:
        return self.verdict == "ALLOW"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason_code": self.reason_code,
            "boundary_version": self.boundary_version,
        }


__all__ = [
    "ExecutionStatus",
    "TERMINAL_STATUSES",
    "ExpectedSideEffect",
    "SideEffectReport",
    "side_effect_report_compatible_with_read_only",
    "ExecutionRequest",
    "ExecutionContext",
    "ExecutionResult",
    "BoundaryDecision",
    "METADATA_ALLOWED_KEYS",
    "is_metadata_allowed",
    "utcnow",
]
