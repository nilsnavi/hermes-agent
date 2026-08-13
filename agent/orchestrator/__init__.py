"""Hermes Agent 2.0 — Runtime Orchestrator (Sprint 1.0.5).

Single bounded execution loop wiring RunEngine → Planner → PlanValidator →
RiskPolicy → ExecutionEngine → ToolRuntime → Verifier → Persistent Store →
RecoveryEngine. HARD guarantee: no loop can run forever — journal-derived
budgets (max_steps / max_tool_calls / max_replans / max_failures /
runtime) terminate even a maliciously CONTINUE-forever planner.

    Request
      │
      ▼
RuntimeOrchestrator ──► RunEngine (create/classify/plan/running/verify)
      │                       │
      │  ExecutionLoop ◄──────┘   (bounded, step-granular)
      │    │ PlanValidator │ RiskPolicy │ DuplicateActionDetector
      │    │ ExecutionEngine (execute_next_step) │ ToolRuntime
      │    └─► Verifier ─► COMPLETED only after ALL steps + verification
      │
      └──► RecoveryEngine (resume / approve / manual review)

Production gateway is NOT integrated (activation is a later sprint).
Standalone package — tests use fake tools + temporary SQLite DBs only.
"""

from .budget import ExecutionBudget
from .decisions import LoopDecision, StopReason
from .events import ORCHESTRATOR_EVENT_TYPES
from .exceptions import (
    BudgetExceeded,
    OrchestrationRefused,
    OrchestratorErrorBase,
    PlanValidationError,
)
from .idempotency import (
    DuplicateActionDetector,
    DuplicateStatus,
    compute_input_hash,
    idempotency_key,
)
from .loop import ExecutionLoop, LoopOutcome
from .models import OrchestrationResult
from .orchestrator import RuntimeOrchestrator, TaskClassifier
from .plan_validation import PlanValidator
from .policy import (
    ConservativeRiskPolicy,
    ExecutionPolicy,
    FailureClass,
    RiskDecision,
    RiskPolicy,
    classify_failure,
    may_retry,
)

__all__ = [
    "RuntimeOrchestrator",
    "TaskClassifier",
    "ExecutionLoop",
    "LoopOutcome",
    "ExecutionBudget",
    "ExecutionPolicy",
    "LoopDecision",
    "StopReason",
    "OrchestrationResult",
    "PlanValidator",
    "RiskPolicy",
    "ConservativeRiskPolicy",
    "RiskDecision",
    "FailureClass",
    "classify_failure",
    "may_retry",
    "DuplicateActionDetector",
    "DuplicateStatus",
    "compute_input_hash",
    "idempotency_key",
    "ORCHESTRATOR_EVENT_TYPES",
    "OrchestratorErrorBase",
    "BudgetExceeded",
    "PlanValidationError",
    "OrchestrationRefused",
]
