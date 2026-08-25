"""Simulation-only recovery classification over durable evidence.

The certified MultiServiceRecoveryCoordinator remains the recovery authority;
this facade only maps canary crash markers into fail-closed dispositions and
never mints execution authority or calls an adapter.
"""
from __future__ import annotations
import dataclasses
from agent.multi_service_recovery import MultiServiceRecoveryCoordinator
from agent.multi_service_execution import build_compensation_bridge_result

CRASH_POINTS=("after-lock","after-approval","after-budget-reserve","after-child-a","before-child-b","after-child-b","before-verify","after-verify","before-simulated-global-commit","after-simulated-global-commit")

@dataclasses.dataclass(frozen=True,slots=True)
class CanaryRecoveryPlan:
 disposition:str
 manual_review:bool
 resume_phase:str
 adapter_calls:int=0
 real_compensation_adapter_calls:int=0

class CanaryRecoveryClassifier:
 certified_coordinator_type=MultiServiceRecoveryCoordinator
 def classify(self,durable_events):
  events=tuple(durable_events)
  if not events:return CanaryRecoveryPlan("MANUAL_REVIEW_REQUIRED",True,"")
  if "UNKNOWN_OUTCOME" in events:return CanaryRecoveryPlan("UNKNOWN_OUTCOME",True,"")
  if "GLOBAL_COMMITTED_SIMULATED" in events:return CanaryRecoveryPlan("TERMINAL_REPLAY",False,"")
  if "CHILD_EFFECT_SIMULATED" in events:return CanaryRecoveryPlan("COMPENSATION_REQUIRED_SIMULATED",False,"COMPENSATION_SIMULATION")
  if "LOCKS_ACQUIRED" in events:return CanaryRecoveryPlan("REVALIDATE_REQUIRED",False,"ADMISSION")
  return CanaryRecoveryPlan("MANUAL_REVIEW_REQUIRED",True,"")

def compensation_steps(execution_order,effect_services,unknown_services=()):
 effect=set(effect_services);unknown=set(unknown_services);steps=[]
 for sid in reversed(tuple(execution_order)):
  op="MANUAL_REVIEW" if sid in unknown else ("COMPENSATE_SIMULATED" if sid in effect else "NOOP")
  steps.append((sid,op))
 return tuple(steps)
REAL_COMPENSATION_ADAPTER_CALLS=0
