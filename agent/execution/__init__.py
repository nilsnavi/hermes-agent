"""Execution Engine (Sprint 1.0.2) — Hermes Agent 2.0 task execution layer.

Builds ON TOP of the Runtime Core (agent/runtime, Sprint 1.0.1) — reuses its
RuntimeEvent audit-trail object; does NOT duplicate the run lifecycle.

    ExecutionPlan   ← models.py   (plan + steps, step statuses)
    ExecutionPlanner← planner.py  (TaskContext → validated plan)
    ToolRegistry    ← registry.py (allowlist: only registered tools run)
    ToolRuntime     ← tool_runtime.py (success/failure/timeout/permission_denied)
    ApprovalManager ← approval.py (PENDING/APPROVED/REJECTED/EXPIRED)
    ExecutionVerifier← verifier.py (result/status/required-fields checks)
    ExecutionEngine ← executor.py (execute_plan → approval gate → verify → complete)
    MemoryStore     ← executor.py (persistence interface, memory backend)

Sprint 1.0.2 is STANDALONE: no production code imports this package; no gateway
/ scheduler / router / config changes. SQLite persistence, real tool connectors
and approval UI are later sprints.
"""

from .approval import ApprovalManager, ApprovalRequest, ApprovalStatus
from .exceptions import (
    ApprovalAlreadyDecided,
    ApprovalExpired,
    ExecutionErrorBase,
    InvalidPlan,
    ToolNotAllowed,
)
from .executor import ExecutionEngine, MemoryExecutionStore
from .models import ExecutionPlan, ExecutionStep, PlanStatus, StepStatus
from .planner import ExecutionPlanner
from .registry import ToolRegistry
from .tool_runtime import ToolResult, ToolRuntime
from .verifier import ExecutionVerifier

__all__ = [
    "ExecutionPlan",
    "ExecutionStep",
    "PlanStatus",
    "StepStatus",
    "ExecutionPlanner",
    "ToolRegistry",
    "ToolRuntime",
    "ToolResult",
    "ApprovalManager",
    "ApprovalRequest",
    "ApprovalStatus",
    "ExecutionVerifier",
    "ExecutionEngine",
    "MemoryExecutionStore",
    "ExecutionErrorBase",
    "InvalidPlan",
    "ToolNotAllowed",
    "ApprovalAlreadyDecided",
    "ApprovalExpired",
]
