"""Verified Tool Executor (Sprint 1.3.2 — VERIFIED TOOL EXECUTION CONTRACT).

The canonical execution contract between the Capability Router / Policy
Engine and verified tool implementations:

    Intent
      ↓
    Capability Router
      ↓
    Policy Engine
      ↓
    VerifiedToolExecutor      ← this package
      ↓
    ExecutionRequest
      ↓
    Tool Adapter
      ↓
    ExecutionResult

The executor is a STANDALONE 2.0 module: stdlib-only imports at module
level, injectable clock, no gateway/scheduler/provider imports, no
shell, no network, no filesystem authority of its own. Real tool
implementations are reached ONLY through verified adapters registered
in a VerifiedToolRegistry that binds to the CapabilityRegistry
descriptors (registry identity required — no arbitrary tool names, no
dynamic import / eval / PATH lookup).

Sprint 1.3.2 creates the canonical contract only. System-level
enforcement (filesystem sandbox, shell policy, network allow/deny,
privilege/PID/environment boundaries) belongs to Sprint 1.3.3 System
Boundary Layer; the injection point is prepared here as
SystemBoundary with a NoopSystemBoundary implementation that grants no
new authority.

Exactly-once: for (run_id, step_id, idempotency_key) at most one
effective adapter execution; duplicates return the prior
receipt/result or DUPLICATE_ACTION. Execution receipts are durable
(survive process restart); a TOOL_STARTED without a terminal event
recovers as UNKNOWN_OUTCOME — never auto-reexecute.
"""

from .adapter import AdapterResult, VerifiedToolAdapter
from .boundary import BoundaryDecision, NoopSystemBoundary, SystemBoundary
from .errors import (
    DUPLICATE_ACTION,
    INVALID_ARGUMENTS,
    INVALID_TOOL_RESULT,
    POLICY_NOT_ALLOWED,
    TOOL_CANCELLED,
    TOOL_EXECUTION_ERROR,
    TOOL_NOT_REGISTERED,
    TOOL_NOT_VERIFIED,
    TOOL_RISK_MISMATCH,
    TOOL_SIDE_EFFECT_VIOLATION,
    TOOL_TIMEOUT,
    UNKNOWN_EXECUTION_OUTCOME,
    CAPABILITY_MISMATCH,
    BOUNDARY_REJECTED,
    ExecutionErrorBase,
    VerifiedToolExecutionError,
)
from .executor import VerifiedToolExecutor
from .flags import (
    EXECUTOR_ENV,
    parse_executor_flag,
    read_executor_flags,
)
from .models import (
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ExpectedSideEffect,
    SideEffectReport,
)
from .receipts import (
    ExecutionReceipt,
    MemoryReceiptStore,
    ReceiptStore,
    SQLiteReceiptStore,
)
from .registry import ToolBinding, VerifiedToolRegistry

__all__ = [
    # models
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionContext",
    "ExecutionStatus",
    "ExpectedSideEffect",
    "SideEffectReport",
    # errors
    "ExecutionErrorBase",
    "VerifiedToolExecutionError",
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
    # executor
    "VerifiedToolExecutor",
    # registry / adapter
    "VerifiedToolRegistry",
    "ToolBinding",
    "VerifiedToolAdapter",
    "AdapterResult",
    # boundary
    "SystemBoundary",
    "NoopSystemBoundary",
    "BoundaryDecision",
    # receipts
    "ExecutionReceipt",
    "ReceiptStore",
    "MemoryReceiptStore",
    "SQLiteReceiptStore",
    # flags
    "parse_executor_flag",
    "read_executor_flags",
    "EXECUTOR_ENV",
]
