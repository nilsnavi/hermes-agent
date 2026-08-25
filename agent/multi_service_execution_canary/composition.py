"""Certified component bindings for the canary composition layer.

This module deliberately contains no coordinator implementation.  It binds the
canary admission to the already-certified lower-layer types and exposes their
identity for architecture verification only.
"""
from __future__ import annotations
import dataclasses
from agent.multi_service_coordination import GlobalTransaction,MultiServiceCoordinator,ServiceSubPlan,PreparedServiceToken
from agent.multi_service_execution import MultiServiceExecutionPlan,MultiServiceExecutionAuthority,ExecutionBarrier,GlobalCommitCoordinator
from agent.multi_service_recovery import MultiServiceRecoveryCoordinator

@dataclasses.dataclass(frozen=True,slots=True)
class CertifiedComponentBindings:
 coordinator:type=MultiServiceCoordinator
 global_transaction:type=GlobalTransaction
 service_subplan:type=ServiceSubPlan
 prepared_token:type=PreparedServiceToken
 execution_plan:type=MultiServiceExecutionPlan
 execution_authority:type=MultiServiceExecutionAuthority
 execution_barrier:type=ExecutionBarrier
 global_commit:type=GlobalCommitCoordinator
 recovery_coordinator:type=MultiServiceRecoveryCoordinator
 real_execution_authority_granted:bool=False

CERTIFIED_COMPONENTS=CertifiedComponentBindings()
