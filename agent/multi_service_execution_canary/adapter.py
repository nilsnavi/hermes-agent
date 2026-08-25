"""Sealed deterministic child simulation adapter; no command surface."""
from __future__ import annotations
from .models import ChildExecutionIntent, SimulatedOutcome
from .registry import CanaryServiceRegistry
_SEAL=object()
class CanaryChildExecutionAdapter:
    __slots__=("_registry","_calls","_seal")
    def __init__(self, *, _seal=None):
        if _seal is not _SEAL: raise TypeError("adapter is runtime sealed")
        self._registry=CanaryServiceRegistry();self._calls=0;self._seal=_seal
    @property
    def calls(self): return self._calls
    def _simulate(self, intent: ChildExecutionIntent, outcome: str="SIMULATED_SUCCESS") -> SimulatedOutcome:
        if type(intent) is not ChildExecutionIntent or self._registry.resolve(intent.service_id) is None: raise PermissionError("exact registered fixture required")
        if intent.operation!="SIMULATE_TWO_REGISTERED_AUX_SERVICES": raise PermissionError("operation denied")
        self._calls+=1
        try:return SimulatedOutcome(outcome)
        except ValueError:return SimulatedOutcome.SIMULATED_UNKNOWN

def _sealed_adapter(): return CanaryChildExecutionAdapter(_seal=_SEAL)
