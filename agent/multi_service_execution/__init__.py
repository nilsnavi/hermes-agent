"""Sprint 1.3.17 — bounded multi-service execution foundation.

Executes the CERTIFIED coordination + recovery + system-boundary layers into a
bounded, FAIL-CLOSED multi-service execution pipeline.  This sprint only.

=====================================================================
REAL MULTI-SERVICE EXECUTION: DISABLED.
REAL ADAPTER CALLS = 0 (the adapter is a deterministic FakeServiceAdapter).
COMPENSATION EXECUTION: SIMULATED ONLY (no real compensation adapter).
SYSTEM_CONTROL = OFF.  GENERIC SERVICE_CONTROL = DENIED.
=====================================================================

The parent multi-service execution authority may exist ONLY when ALL child
execution authorities are independently valid.  This module never grants
authority the child policy did not already grant, never bypasses a child gate,
never converts a child DENY/UNKNOWN into ALLOW, and never lets an adapter
success commit globally by itself.

The executor (\`BoundedMultiServiceExecutor\`) is intentionally NOT part of the
public API.  Authority is sealed and minted only inside the pipeline runtime.

Standalone, stdlib-only, composed over:
    agent.multi_service_coordination   (MultiServiceChangePlan / store)
    agent.multi_service_recovery       (recovery & compensation semantics)
    agent.system_boundary              (SystemBoundaryLayer)
    agent.service_restart_policy._durable  (JsonTransaction)
"""
from __future__ import annotations

from .authority import ExecutionRuntime, MultiServiceExecutionAuthority
from .barrier import BarrierVerdict, ExecutionBarrier
from .commit import GlobalCommitCoordinator
from .compensation_bridge import CompensationBridgeResult, build_compensation_bridge_result
from .exceptions import (
    AuthorityDenied,
    DevelopmentGateError,
    ExecutionDisabled,
    InvalidExecutionPlan,
    MultiServiceExecutionError,
    ReceiptStoreError,
    RevalidateRequired,
)
from .fake_adapter import FakeAdapterResult, FakeServiceAdapter
from .flags import (
    ALLOWED_MODES,
    ENABLED,
    MODE,
    live_execution_permitted,
    multi_exec_enabled,
    multi_exec_mode,
)
from .idempotency import ExecutionIdempotencyStore
from .locks import lock_owner_valid, lockset_digest
from .budget import BudgetVerdict, ExecutionBudget, ExecutionBudgetLimits
from .approval import approval_binding_valid, approval_ttl_valid
from .models import (
    AdapterOutcome,
    ChildExecutionBinding,
    ChildExecutionState,
    ExecutionMode,
    ExecutionReceipt,
    GlobalExecutionState,
    MultiServiceExecutionPlan,
    TERMINAL_EXECUTION_STATES,
    can_transition,
    semantic_execution_key,
    service_set_hash,
)
from .outcome import adapter_outcome_to_child_state, normalize_adapter_result
from .pipeline import ExecutionPipeline, build_execution_plan
from .receipt import ExecutionReceiptStore
from .recovery_bridge import recovery_allows_execution, recovery_requires_manual
from .stabilization import StabilizationResult, stabilization_check
from .telemetry import ExecutionTelemetry
from .verifier import VerificationResult, VerificationState, verify_child

__version__ = "1.3.17"

__all__ = [
    "ALLOWED_MODES",
    "AdapterOutcome",
    "AuthorityDenied",
    "BarrierVerdict",
    "BudgetVerdict",
    "ChildExecutionBinding",
    "ChildExecutionState",
    "CompensationBridgeResult",
    "DevelopmentGateError",
    "ENABLED",
    "ExecutionBarrier",
    "ExecutionBudget",
    "ExecutionBudgetLimits",
    "ExecutionDisabled",
    "ExecutionIdempotencyStore",
    "ExecutionMode",
    "ExecutionPipeline",
    "ExecutionReceipt",
    "ExecutionReceiptStore",
    "ExecutionRuntime",
    "ExecutionTelemetry",
    "FakeAdapterResult",
    "FakeServiceAdapter",
    "GlobalCommitCoordinator",
    "GlobalExecutionState",
    "InvalidExecutionPlan",
    "MODE",
    "MultiServiceExecutionAuthority",
    "MultiServiceExecutionError",
    "MultiServiceExecutionPlan",
    "ReceiptStoreError",
    "RevalidateRequired",
    "StabilizationResult",
    "TERMINAL_EXECUTION_STATES",
    "VerificationResult",
    "VerificationState",
    "adapter_outcome_to_child_state",
    "approval_binding_valid",
    "approval_ttl_valid",
    "build_compensation_bridge_result",
    "build_execution_plan",
    "can_transition",
    "live_execution_permitted",
    "lock_owner_valid",
    "lockset_digest",
    "multi_exec_enabled",
    "multi_exec_mode",
    "normalize_adapter_result",
    "recovery_allows_execution",
    "recovery_requires_manual",
    "semantic_execution_key",
    "service_set_hash",
    "stabilization_check",
    "verify_child",
]