"""Exact static non-systemd two-fixture registry."""
from __future__ import annotations
import hashlib
from types import MappingProxyType
from .models import CanaryServiceProfile
_A = CanaryServiceProfile("canary-service-a", "hermes-owned-fixture-a-v1")
_B = CanaryServiceProfile("canary-service-b", "hermes-owned-fixture-b-v1")
_STATIC = MappingProxyType({_A.service_id: _A, _B.service_id: _B})
_GRAPH = MappingProxyType({_A.service_id: (), _B.service_id: (_A.service_id,)})

def _digest(lines) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()

class CanaryServiceRegistry:
    __slots__ = ("_profiles", "_graph")
    def __init__(self) -> None:
        self._profiles = MappingProxyType(dict(_STATIC)); self._graph = MappingProxyType(dict(_GRAPH))
    @property
    def digest(self) -> str:
        return _digest(f"{k}\0{v.identity}\0{v.service_class}\0{v.criticality}\0{v.blast}\0{v.fixture_kind}" for k,v in sorted(self._profiles.items()))
    @property
    def graph_digest(self) -> str:
        return _digest(f"{k}:{','.join(v)}" for k,v in sorted(self._graph.items()))
    def service_ids(self) -> tuple[str, ...]: return tuple(sorted(self._profiles))
    def profiles(self) -> tuple[CanaryServiceProfile, ...]: return tuple(self._profiles[k] for k in self.service_ids())
    def resolve(self, service_id: str): return self._profiles.get(service_id)
    def execution_order(self) -> tuple[str, ...]: return ("canary-service-a", "canary-service-b")
    def compensation_order(self) -> tuple[str, ...]: return tuple(reversed(self.execution_order()))
