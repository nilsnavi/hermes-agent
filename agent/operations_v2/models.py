"""Operations DTOs (Sprint 1.0.6.3) — safe observability models.

Design rules:

- A summary/timeline DTO NEVER carries raw payloads: no prompts, no
  raw tool arguments, no raw outputs, no secrets. Fields are scalar
  or structured enums only.
- Enums serialize as their ``.value`` so JSON output has a STABLE
  schema for automation.
- Timestamps stay ISO-8601 UTC strings.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ── enums ────────────────────────────────────────────────────────────


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class DecisionReasonCode(Enum):
    """Structured approval decision reasons (§27)."""

    OPERATOR_APPROVED = "operator_approved"
    OPERATOR_REJECTED = "operator_rejected"
    EXPIRED = "expired"
    POLICY_DENIED = "policy_denied"
    RUN_CANCELLED = "run_cancelled"
    STALE_VERSION = "stale_version"


class AlertCode(Enum):
    """Structured health findings (§47)."""

    SAFETY_WRITE_EXECUTED = "SAFETY_WRITE_EXECUTED"
    DUPLICATE_RESPONSE = "DUPLICATE_RESPONSE"
    SECRET_LEAK = "SECRET_LEAK"
    ORDINARY_TRAFFIC_V2 = "ORDINARY_TRAFFIC_V2"
    DB_INTEGRITY_ERROR = "DB_INTEGRITY_ERROR"
    DB_LOCK_LOOP = "DB_LOCK_LOOP"
    GATEWAY_RESTART_LOOP = "GATEWAY_RESTART_LOOP"
    CANARY_FAILURE_RATE_HIGH = "CANARY_FAILURE_RATE_HIGH"
    STALE_APPROVAL = "STALE_APPROVAL"
    MANUAL_REVIEW_PENDING = "MANUAL_REVIEW_PENDING"
    ROUTER_UNSAFE_PREDICTION = "ROUTER_UNSAFE_PREDICTION"
    ROUTER_ERROR_RATE_HIGH = "ROUTER_ERROR_RATE_HIGH"


class ErrorCode(Enum):
    """Structured error taxonomy (§14)."""

    INVALID_PLAN = "INVALID_PLAN"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_FAILED = "TOOL_FAILED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# ── operator identity (§24) ──────────────────────────────────────────


@dataclass(frozen=True)
class OperatorIdentity:
    """Minimal operator foundation. CLI/internal only — no full IAM."""

    operator_id: str
    source: str = "cli"
    roles: frozenset = frozenset()
    authenticated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operator_id": self.operator_id,
            "source": self.source,
            "roles": sorted(self.roles),
            "authenticated": self.authenticated,
        }


# ── run summary (§8) ─────────────────────────────────────────────────


@dataclass
class RunSummary:
    run_id: str
    status: str
    task_type: str
    created_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    duration_ms: Optional[int]
    plan_status: Optional[str]
    step_count: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    tool_calls: int = 0
    approval_count: int = 0
    stop_reason: Optional[str] = None
    recovery_disposition: Optional[str] = None
    last_event_type: Optional[str] = None
    last_event_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "task_type": self.task_type,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "plan_status": self.plan_status,
            "step_count": self.step_count,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "tool_calls": self.tool_calls,
            "approval_count": self.approval_count,
            "stop_reason": self.stop_reason,
            "recovery_disposition": self.recovery_disposition,
            "last_event_type": self.last_event_type,
            "last_event_at": self.last_event_at,
        }


# ── timeline (§9) ────────────────────────────────────────────────────


@dataclass
class RunTimelineItem:
    event_id: int
    timestamp: Optional[str]
    event_type: str
    step_id: Optional[str]
    tool_name: Optional[str]
    status: Optional[str]
    reason_code: Optional[str]
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "reason_code": self.reason_code,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
        }


# ── approval view (§40) ──────────────────────────────────────────────


@dataclass
class ApprovalView:
    approval_id: str
    run_id: str
    step_id: str
    tool: Optional[str]
    task_type: Optional[str]
    reason: str
    status: str
    risk: Optional[str]
    side_effect: Optional[str]
    created_at: Optional[str]
    expires_at: Optional[str]
    decided_at: Optional[str]
    decided_by: Optional[str]
    decision_source: Optional[str]
    decision_reason_code: Optional[str]
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "tool": self.tool,
            "task_type": self.task_type,
            "reason": self.reason,
            "status": self.status,
            "risk": self.risk,
            "side_effect": self.side_effect,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "decision_source": self.decision_source,
            "decision_reason_code": self.decision_reason_code,
            "version": self.version,
        }


@dataclass
class ApprovalDecision:
    """Durable decision outcome + metadata (durable in the approvals row)."""

    approval_id: str
    run_id: str
    step_id: str
    decision: str
    reason_code: Optional[str]
    decided_by: str
    decision_source: str
    decided_at: Optional[str]
    version: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "decided_by": self.decided_by,
            "decision_source": self.decision_source,
            "decided_at": self.decided_at,
            "version": self.version,
        }


# ── manual review (§42) ──────────────────────────────────────────────


@dataclass
class ManualReviewItemDTO:
    run_id: str
    step_id: Optional[str]
    tool: Optional[str]
    reason: str
    last_event_type: Optional[str]
    last_event_at: Optional[str]
    recovery_disposition: str
    created_at: Optional[str]
    recommended_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step_id": self.step_id,
            "tool": self.tool,
            "reason": self.reason,
            "last_event_type": self.last_event_type,
            "last_event_at": self.last_event_at,
            "recovery_disposition": self.recovery_disposition,
            "created_at": self.created_at,
            "recommended_actions": list(self.recommended_actions),
        }


# ── stale runs (§44) ─────────────────────────────────────────────────


@dataclass
class StaleRun:
    run_id: str
    status: str
    disposition: str
    waiting_since: Optional[str]
    stale_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "disposition": self.disposition,
            "waiting_since": self.waiting_since,
            "stale_reason": self.stale_reason,
        }


# ── health (§17) ─────────────────────────────────────────────────────


@dataclass
class RuntimeV2Health:
    status: str
    enabled: bool = False
    shadow: bool = False
    canary: bool = False
    persistence: bool = False
    schema_ready: bool = False
    gateway_alive: bool = False
    db_integrity_last_known: str = "unknown"
    incomplete_runs: int = 0
    waiting_approvals: int = 0
    manual_reviews: int = 0
    last_successful_canary_at: Optional[str] = None
    last_failed_canary_at: Optional[str] = None
    kill_switch_available: bool = False
    canary_allowlist_active: bool = False
    read_only_enforced: bool = False
    intent_router_enabled: bool = False
    intent_router_mode: str = "off"
    router_error_rate: Optional[float] = None
    unsafe_prediction_count: int = 0
    router_decisions_total: int = 0
    findings: List[Dict[str, Any]] = field(default_factory=list)
    slo: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "runtime_v2": {
                "enabled": self.enabled,
                "shadow": self.shadow,
                "canary": self.canary,
                "persistence": self.persistence,
                "schema_ready": self.schema_ready,
            },
            "gateway_alive": self.gateway_alive,
            "db_integrity_last_known": self.db_integrity_last_known,
            "incomplete_runs": self.incomplete_runs,
            "waiting_approvals": self.waiting_approvals,
            "manual_reviews": self.manual_reviews,
            "last_successful_canary_at": self.last_successful_canary_at,
            "last_failed_canary_at": self.last_failed_canary_at,
            "kill_switch_available": self.kill_switch_available,
            "canary_allowlist_active": self.canary_allowlist_active,
            "read_only_enforced": self.read_only_enforced,
            "intent_router": {
                "enabled": self.intent_router_enabled,
                "mode": self.intent_router_mode,
                "router_error_rate": self.router_error_rate,
                "unsafe_prediction_count": self.unsafe_prediction_count,
                "decisions_total": self.router_decisions_total,
            },
            "findings": list(self.findings),
            "slo": dict(self.slo),
        }
