"""Sprint 1.3.9 — dependency graph, provenance, health, blast, risk, reload/restart."""
from __future__ import annotations

import pytest

from agent.service_foundation import (BlastRadius, Eligibility, IdentityResult, Operation, evaluate)
from agent.service_foundation.graph import GraphStatus, ServiceDependencyGraph
from agent.service_foundation.models import EdgeType, Provenance
from agent.service_foundation.registry import ServiceRegistry


def _g(*, stale=False, partial=False, unresolved=0, dependents=False):
    g = ServiceDependencyGraph(partial=partial, unresolved=unresolved, stale=stale,
                               built_at=0 if stale else None)
    g.add_edge("hermes-aux-agent", "test-echo", EdgeType.REQUIRES, Provenance.SYSTEMD_DECLARED)
    if dependents:
        g.add_edge("db", "hermes-aux-agent", EdgeType.CONSUMED_BY, Provenance.INFERRED)
    return g


def _aux_verdict(g, op=Operation.RELOAD_ELIGIBILITY):
    r = ServiceRegistry()
    return evaluate(r.get("hermes-aux-agent"), IdentityResult.VERIFIED, g, op,
                    health_ok=True, validator_ok=True, rollback_proven=True)


def test_graph_healthy_provenance():
    g = _g()
    assert g.status() is GraphStatus.HEALTHY
    assert g.edges["hermes-aux-agent"][0]["provenance"] == "systemd_declared"


def test_graph_stale_denies():
    assert _aux_verdict(_g(stale=True)) is Eligibility.GRAPH_STALE


def test_graph_unavailable_denies():
    assert _aux_verdict(None) is not Eligibility.ELIGIBLE_FOR_FUTURE_RELOAD_CANARY


def test_graph_dependents_raise_blast():
    g = _g(dependents=True)
    assert g.has_dependents("hermes-aux-agent") is True
    assert _aux_verdict(g) is not Eligibility.ELIGIBLE_FOR_FUTURE_RELOAD_CANARY


def test_digest_stable():
    assert _g().digest() == _g().digest()


def test_reload_requires_validator_health():
    r = ServiceRegistry()
    p = r.get("hermes-aux-agent")
    g = _g()
    # missing validator
    assert evaluate(p, IdentityResult.VERIFIED, g, Operation.RELOAD_ELIGIBILITY,
                    health_ok=True, validator_ok=False, rollback_proven=True) is Eligibility.CONFIG_VALIDATOR_MISSING
    # missing health
    assert evaluate(p, IdentityResult.VERIFIED, g, Operation.RELOAD_ELIGIBILITY,
                    health_ok=False, validator_ok=True, rollback_proven=True) is Eligibility.HEALTH_CONTRACT_MISSING
    # rollback unproven
    assert evaluate(p, IdentityResult.VERIFIED, g, Operation.RELOAD_ELIGIBILITY,
                    health_ok=True, validator_ok=True, rollback_proven=False) is Eligibility.ROLLBACK_UNPROVEN
