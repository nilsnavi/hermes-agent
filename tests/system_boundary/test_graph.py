"""Sprint 1.3.3 §32-§38/§65/§66 — SERVICE GRAPH, TRUST, BLAST RADIUS.

Synthetic graph (§65): nginx → config/port 443/certificate/backend →
postgres → volume. Provenance trust (§66): LEARNED/INFERRED edges may
only RAISE risk, never grant PASS. UNKNOWN/PARTIAL dependency set !=
EMPTY. Blast radius: UNKNOWN != NONE.
"""

import pytest

from agent.system_boundary import blast_radius as br
from agent.system_boundary import models as m
from agent.system_boundary import service_graph as sg


# ── graph construction (§32) ────────────────────────────────────────

def test_build_synthetic_nginx_graph():
    g = sg.ServiceGraph()
    g.add_node("nginx", node_type="SERVICE")
    g.add_node("nginx.conf", node_type="CONFIG")
    g.add_node("443", node_type="PORT")
    g.add_node("cert", node_type="CERTIFICATE")
    g.add_node("backend", node_type="SERVICE")
    g.add_node("postgres", node_type="DATABASE")
    g.add_node("pg-volume", node_type="VOLUME")

    g.add_edge("nginx", "nginx.conf", "READS", "STATIC_VERIFIED")
    g.add_edge("nginx", "443", "LISTENS_ON", "STATIC_VERIFIED")
    g.add_edge("nginx", "cert", "USES_CERTIFICATE", "STATIC_VERIFIED")
    g.add_edge("nginx", "backend", "DEPENDS_ON", "STATIC_VERIFIED")
    g.add_edge("backend", "postgres", "DEPENDS_ON", "STATIC_VERIFIED")
    g.add_edge("postgres", "pg-volume", "MOUNTS", "STATIC_VERIFIED")

    assert g.has_node("nginx")
    assert g.node_count() == 7
    assert g.edge_count() == 6


def test_graph_provenance_recorded():
    g = sg.ServiceGraph()
    g.add_node("nginx", node_type="SERVICE")
    g.add_edge("nginx", "backend", "DEPENDS_ON", "INFERRED")
    edges = g.edges_from("nginx")
    assert any(e.provenance == "INFERRED" for e in edges)


def test_graph_dependencies_bounded():
    g = sg.ServiceGraph()
    g.add_node("nginx", node_type="SERVICE")
    g.add_node("postgres", node_type="DATABASE")
    g.add_node("unknown-dep", node_type="UPSTREAM")
    g.add_edge("nginx", "postgres", "DEPENDS_ON", "STATIC_VERIFIED")
    g.add_edge("nginx", "unknown-dep", "DEPENDS_ON", "INFERRED")
    deps = g.dependencies("nginx")
    assert "postgres" in deps
    assert "unknown-dep" in deps


def test_graph_unknown_dependency_raises_risk_not_grants():
    """An INFERRED/LEARNED dependency must raise the risk floor for a
    mutation of nginx, never prove safety."""
    g = sg.ServiceGraph()
    g.add_node("nginx", node_type="SERVICE")
    g.add_node("unknown-dep", node_type="UPSTREAM")
    g.add_edge("nginx", "unknown-dep", "DEPENDS_ON", "LEARNED")
    radius = br.blast_radius_for_target("nginx", g)
    # UNKNOWN-ish dependency → radius must not be NONE
    assert radius in ("SERVICE", "MULTI_SERVICE", "HOST", "NETWORK",
                      "UNKNOWN")


def test_learned_edge_cannot_reduce_risk():
    from agent.system_boundary.risk import apply_risk_floor
    # LEARNED edge presence can only raise; absence can't prove safety
    assert apply_risk_floor("READ_ONLY", "SERVICE") == "SERVICE"


# ── graph health (§37) ──────────────────────────────────────────────

def test_partial_graph_not_empty_deps():
    g = sg.ServiceGraph(health="PARTIAL")
    g.add_node("nginx", node_type="SERVICE")
    # PARTIAL graph: unknown deps must NOT be treated as empty
    assert g.health == "PARTIAL"
    assert g.dependency_state_known("nginx") is False


def test_unavailable_graph_forces_revalidation():
    from agent.system_boundary.verifier import verify_before_execute
    from agent.system_boundary.boundary import SystemBoundaryLayer

    sbl = SystemBoundaryLayer(mode="enforce", graph=None)
    preflight = sbl.preflight_command(
        command="systemctl restart nginx", tool_name="systemctl",
        capability="SERVICE_CONTROL", cwd="/")
    decision = sbl.verify_command_preflight(preflight)
    assert decision.verdict in ("BLOCK", "REVALIDATE_REQUIRED")


# ── blast radius (§39-§41) ──────────────────────────────────────────

def test_blast_radius_canonical_values():
    for v in ("NONE", "LOCAL", "SERVICE", "MULTI_SERVICE", "HOST",
              "NETWORK", "UNKNOWN"):
        assert v in br.BLAST_RADIUS_VALUES


def test_blast_radius_unknown_neq_none():
    assert br.BLAST_RADIUS_VALUES["UNKNOWN"] != \
        br.BLAST_RADIUS_VALUES["NONE"]


def test_blast_radius_local_does_not_raise():
    assert br.risk_floor_for_radius("LOCAL") == "READ_ONLY"


def test_blast_radius_risk_floors():
    assert br.risk_floor_for_radius("SERVICE") == "SYSTEM"
    assert br.risk_floor_for_radius("MULTI_SERVICE") == "SYSTEM"
    assert br.risk_floor_for_radius("HOST") == "SYSTEM"
    assert br.risk_floor_for_radius("NETWORK") == "CRITICAL"
    assert br.risk_floor_for_radius("UNKNOWN") == "CRITICAL"


def test_blast_radius_cycle_safe():
    g = sg.ServiceGraph()
    for n in ("a", "b", "c"):
        g.add_node(n, node_type="SERVICE")
    g.add_edge("a", "b", "DEPENDS_ON", "STATIC_VERIFIED")
    g.add_edge("b", "c", "DEPENDS_ON", "STATIC_VERIFIED")
    g.add_edge("c", "a", "DEPENDS_ON", "STATIC_VERIFIED")
    # must not hang; returns a bounded radius
    radius = br.blast_radius_for_target("a", g)
    assert radius in br.BLAST_RADIUS_VALUES


def test_blast_radius_budgeted():
    g = sg.ServiceGraph()
    for i in range(20):
        g.add_node(f"svc{i}", node_type="SERVICE")
    for i in range(19):
        g.add_edge(f"svc{i}", f"svc{i+1}", "DEPENDS_ON",
                   "STATIC_VERIFIED")
    radius = br.blast_radius_for_target("svc0", g, max_depth=3)
    assert radius in br.BLAST_RADIUS_VALUES
