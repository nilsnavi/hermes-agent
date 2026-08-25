"""Immutable exact service-set normalization."""
from __future__ import annotations
from .models import BASELINE_SHA,CanaryServiceSet,OPERATION
from .registry import CanaryServiceRegistry

def build_service_set(service_ids, registry: CanaryServiceRegistry, *, baseline_sha=BASELINE_SHA, generation=1, now=0.0, ttl=300.0):
    ids=tuple(sorted(service_ids))
    exact=registry.service_ids()
    if ids!=exact: raise ValueError("exact two-service canary set required")
    profiles=tuple(registry.resolve(x) for x in ids)
    if any(p is None for p in profiles):raise ValueError("unregistered service")
    return CanaryServiceSet(ids,profiles,registry.digest,registry.graph_digest,baseline_sha,generation,OPERATION,"MEDIUM_MUTATION_MODEL","MULTI_SERVICE",(),now,now+ttl)
