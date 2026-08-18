"""Sprint 1.3.3 §54/§85 — PERFORMANCE GATES.

Pure classification p95 < 1 ms; cached graph p95 < 2 ms; path
resolution p95 < 2 ms where filesystem allows. Sample counts are
recorded — no single-shot timing claims.
"""

import statistics
import time

from agent.system_boundary import effective_action as ea
from agent.system_boundary import models as m
from agent.system_boundary import path_resolver as pr


def _p95(samples):
    return statistics.quantiles(sorted(samples), n=20)[18]


def test_pure_classification_p95_below_1ms():
    samples = []
    for _ in range(300):
        t0 = time.perf_counter()
        r = ea.classify_command("systemctl status nginx")
        assert r.effective_action_class == m.EffectiveActionClass.READ
        samples.append((time.perf_counter() - t0) * 1000)
    assert _p95(samples) < 1.0, f"p95={_p95(samples):.3f}ms"


def test_mutation_classification_p95_below_1ms():
    samples = []
    for _ in range(300):
        t0 = time.perf_counter()
        r = ea.classify_command(
            "systemctl --user restart hermes-gateway")
        assert r.self_control is True
        samples.append((time.perf_counter() - t0) * 1000)
    assert _p95(samples) < 1.0, f"p95={_p95(samples):.3f}ms"


def test_path_resolution_p95_below_2ms():
    samples = []
    for _ in range(200):
        t0 = time.perf_counter()
        r = pr.resolve_path("/etc/nginx/nginx.conf", cwd="/")
        assert r.resource_class == m.ResourceClass.SYSTEM_CONFIG
        samples.append((time.perf_counter() - t0) * 1000)
    assert _p95(samples) < 2.0, f"p95={_p95(samples):.3f}ms"


def test_cached_graph_lookup_p95_below_2ms():
    from agent.system_boundary import service_graph as sg
    from agent.system_boundary import blast_radius as br

    g = sg.ServiceGraph()
    for i in range(10):
        g.add_node(f"svc{i}", node_type="SERVICE")
    for i in range(9):
        g.add_edge(f"svc{i}", f"svc{i+1}", "DEPENDS_ON",
                   "STATIC_VERIFIED")

    samples = []
    for _ in range(200):
        t0 = time.perf_counter()
        br.blast_radius_for_target("svc0", g, max_depth=3)
        samples.append((time.perf_counter() - t0) * 1000)
    assert _p95(samples) < 2.0, f"p95={_p95(samples):.3f}ms"
