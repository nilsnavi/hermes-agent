"""Separate in-memory canary simulation budget; never production budget."""
from __future__ import annotations
import dataclasses
@dataclasses.dataclass(frozen=True,slots=True)
class CanaryBudgetLimits:max_attempts_per_hour:int=10;max_simulated_success_per_hour:int=5
@dataclasses.dataclass(slots=True)
class CanarySimulationBudget:
 limits:CanaryBudgetLimits=CanaryBudgetLimits();attempts:int=0;successes:int=0
 def available(self):return self.attempts<self.limits.max_attempts_per_hour and self.successes<self.limits.max_simulated_success_per_hour
 def consume(self,*,success=False):
  if not self.available():return False
  self.attempts+=1;self.successes+=int(success);return True
