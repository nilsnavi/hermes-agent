"""Sprint 1.3.9 — service risk, blast radius, criticality (monotonic)."""
from __future__ import annotations

from .models import (BlastRadius, Criticality, RiskClass, ServiceClass)

_RANK = {Criticality.LOW: 1, Criticality.MEDIUM: 2, Criticality.HIGH: 3, Criticality.CRITICAL: 4}
_RISKRANK = {RiskClass.NO_MUTATION: 0, RiskClass.LOW: 1, RiskClass.MEDIUM: 2,
             RiskClass.HIGH: 3, RiskClass.CRITICAL: 4}


def risk_for(profile_risk: RiskClass, criticality: Criticality, *, dependents: int,
             graph_unknown: bool, health_unknown: bool, rollback_unsupported: bool,
             identity_ok: bool, blast: BlastRadius) -> RiskClass:
    """Risk is monotonic: only ever raises from profile baseline."""
    base = max(_RISKRANK[profile_risk], _RANK[criticality] - 2)
    if dependents > 0:
        base += 1
    if graph_unknown:
        base += 1
    if health_unknown:
        base += 1
    if rollback_unsupported:
        base += 1
    if not identity_ok:
        base += 2
    if blast in (BlastRadius.MULTI_SERVICE, BlastRadius.HOST, BlastRadius.NETWORK,
                 BlastRadius.CRITICAL, BlastRadius.UNKNOWN):
        base += 2
    return RiskClass(min(4, base))


def blast_radius(graph, profile) -> BlastRadius:
    if profile is None:
        return BlastRadius.UNKNOWN
    if not graph or graph.status().value == "unavailable":
        return BlastRadius.UNKNOWN
    if graph.has_dependents(profile.service_id):
        return BlastRadius.MULTI_SERVICE
    return BlastRadius.SERVICE


def criticality_of(profile) -> Criticality:
    return profile.criticality
