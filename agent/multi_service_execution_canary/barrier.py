"""Canary barrier composes the certified execution barrier type."""
from __future__ import annotations
from dataclasses import dataclass
from agent.multi_service_execution import ExecutionBarrier as CertifiedExecutionBarrier
@dataclass(frozen=True,slots=True)
class CanaryBarrierResult:ready:bool;blocked_by:tuple[str,...]=()
class CanaryExecutionBarrier:
 certified_type=CertifiedExecutionBarrier
 def evaluate(self,**gates):
  blocked=tuple(k for k,v in gates.items() if not v)
  return CanaryBarrierResult(not blocked,blocked)
