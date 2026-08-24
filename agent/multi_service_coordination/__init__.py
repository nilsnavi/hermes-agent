"""Sprint 1.3.15 — bounded multi-service coordination foundation.

SHADOW / REHEARSAL ONLY.  NO LIVE EXECUTION.
=============================================

This module proves the *correctness* of orchestrating a coordinated change
across several services WITHOUT granting any new production mutation
authority.  It works on top of the existing safety layers:

    CapabilityPolicyEngine
    -> VerifiedToolExecutor
    -> SystemBoundaryLayer
    -> TransactionalChangePipeline
    -> LimitedProductionMutationPolicy
    -> ServiceFoundation
    -> LimitedServiceReloadPolicy
    -> RestartFoundation
    -> LimitedRestartPolicy
    -> MultiServiceCoordinator        <-- this module

The coordinator NEVER:
    * resolves a new operation
    * raises authority
    * adds a service to any registry
    * bypasses a per-service policy, approval, lock, budget, breaker,
      health, rollback or idempotency gate
    * turns a child DENY into an ALLOW
    * performs any real child execution (execution_guard always returns
      MULTI_SERVICE_EXECUTION_DISABLED; adapter calls == 0)

Every child service must still traverse its OWN full policy chain.  This
module only aggregates their decisions and guarantees all-or-nothing
coordination, canonical (deadlock-free) lock ordering and deterministic
compensation — all authenticated by a durable, exactly-once journalled
shadow transaction.

Standalone, stdlib-only.  Durable JSON via the shared JsonTransaction helper.
"""
from .flags import ALLOWED_MODES, multi_coord_enabled, multi_coord_mode
from .models import (
    BlastRadius,
    CompensationPlan,
    CompensationStep,
    CoordinatorState,
    GlobalOutcome,
    MultiServiceChangePlan,
    MultiServiceExecutionPermit,
    PrepareBarrier,
    PreparedServiceToken,
    ServiceSubPlan,
    ServiceTransaction,
)
from .transaction import GlobalTransaction, MultiServiceCoordinator
from .execution_guard import execution_disabled, MULTI_SERVICE_EXECUTION_DISABLED

__all__ = [
    "ALLOWED_MODES",
    "BlastRadius",
    "CompensationPlan",
    "CompensationStep",
    "CoordinatorState",
    "GlobalOutcome",
    "GlobalTransaction",
    "MultiServiceChangePlan",
    "MultiServiceExecutionPermit",
    "MULTI_SERVICE_EXECUTION_DISABLED",
    "MultiServiceCoordinator",
    "PrepareBarrier",
    "PreparedServiceToken",
    "ServiceSubPlan",
    "ServiceTransaction",
    "execution_disabled",
    "multi_coord_enabled",
    "multi_coord_mode",
]