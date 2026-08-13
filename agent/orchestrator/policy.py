"""Execution policy + risk policy (Sprint 1.0.5).

Conservative defaults: no auto-retry, no replanning, bounded steps/tools/
replans/failures/runtime. The orchestrator NEVER runs without a policy —
an unbounded loop is impossible by construction.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from agent.execution.registry import SideEffectClass, ToolMetadata
from agent.runtime.context import TaskContext


@dataclass(frozen=True)
class ExecutionPolicy:
    max_steps: int = 20
    max_tool_calls: int = 10
    max_replans: int = 2
    max_failures: int = 3
    max_runtime_seconds: float = 300.0
    max_retries: int = 0  # per-step retries ONLY for idempotent tools
    stop_on_manual_review: bool = True
    stop_on_approval: bool = True
    allow_replanning: bool = False
    model_profile: str = "BALANCED"


class FailureClass(Enum):
    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    AMBIGUOUS = "ambiguous"


def classify_failure(result_status: str, metadata: ToolMetadata) -> FailureClass:
    """Map a ToolResult status to the retry taxonomy.

    - timeout → RETRYABLE (temporary transport);
    - permission_denied / not_allowed / validation → NON_RETRYABLE;
    - failure → RETRYABLE only when the tool is idempotent AND read-only
      (a safe fake/idempotent retry); everything else NON_RETRYABLE.
    - AMBIGUOUS is journal-derived (TOOL_STARTED without TOOL_COMPLETED)
      and never comes from a result status.
    """
    if result_status == "timeout":
        return FailureClass.RETRYABLE
    if result_status in ("permission_denied", "not_allowed"):
        return FailureClass.NON_RETRYABLE
    if result_status == "failure":
        if metadata.idempotent and metadata.side_effect_class is SideEffectClass.READ_ONLY:
            return FailureClass.RETRYABLE
        return FailureClass.NON_RETRYABLE
    return FailureClass.NON_RETRYABLE


def may_retry(
    failure_class: FailureClass,
    metadata: ToolMetadata,
    attempts_used: int,
    policy: ExecutionPolicy,
) -> bool:
    """Retry decision (§30): READ_ONLY+idempotent retry; REVERSIBLE_WRITE
    only with an idempotency key (the orchestrator always derives one);
    IRREVERSIBLE_WRITE / UNKNOWN / non-idempotent NEVER auto-retry."""
    if failure_class is not FailureClass.RETRYABLE:
        return False
    if attempts_used >= policy.max_retries + 1:
        return False
    if not metadata.idempotent:
        return False
    if metadata.side_effect_class is SideEffectClass.READ_ONLY:
        return True
    if metadata.side_effect_class is SideEffectClass.REVERSIBLE_WRITE:
        return True  # idempotency key always derived for a step attempt
    return False  # IRREVERSIBLE_WRITE / UNKNOWN — never


# ── risk policy ──────────────────────────────────────────────────────


class RiskDecision(Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class RiskPolicy(Protocol):
    """Interface hook — a full permission engine is a later sprint."""

    def evaluate(
        self,
        step,
        metadata: ToolMetadata,
        context: TaskContext,
    ) -> RiskDecision: ...


class ConservativeRiskPolicy:
    """Default conservative policy (fail secure):

    - TaskContext.risk_level == "critical" → REQUIRE_APPROVAL;
    - tool side-effect class IRREVERSIBLE_WRITE → REQUIRE_APPROVAL;
    - tool name in TaskContext.metadata["deny_tools"] → DENY;
    - otherwise ALLOW.
    """

    def evaluate(
        self,
        step,
        metadata: ToolMetadata,
        context: TaskContext,
    ) -> RiskDecision:
        deny_tools = context.metadata.get("deny_tools") or []
        if step.tool in deny_tools:
            return RiskDecision.DENY
        if context.risk_level == "critical":
            return RiskDecision.REQUIRE_APPROVAL
        if metadata.side_effect_class is SideEffectClass.IRREVERSIBLE_WRITE:
            return RiskDecision.REQUIRE_APPROVAL
        return RiskDecision.ALLOW


__all__ = [
    "ExecutionPolicy",
    "FailureClass",
    "classify_failure",
    "may_retry",
    "RiskDecision",
    "RiskPolicy",
    "ConservativeRiskPolicy",
]
