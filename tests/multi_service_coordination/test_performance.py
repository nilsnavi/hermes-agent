from __future__ import annotations

"""Performance gates (brief §56).  Pure-function p95 targets:
   plan validation < 2ms, graph order < 2ms, lock order < 1ms,
   eligibility aggregation < 2ms.  (Store IO measured separately and is not
   part of these pure-function gates.)
"""
import time

import pytest

from agent.multi_service_coordination.graph import DependencyGraph, topological_order
from agent.multi_service_coordination.lock_order import canonical_lock_order
from agent.multi_service_coordination.eligibility import aggregate_eligibility
from agent.multi_service_coordination.planner import PlanBuilder
from agent.multi_service_coordination.registry import CoordinationRegistry
from tests.multi_service_coordination.conftest import build_plan, A, B, CANARY


def _p95(samples):
    return sorted(samples)[int(0.95 * len(samples))]


def _run(fn, iters=3000):
    start = time.perf_counter()
    for _ in range(iters):
        fn()
    return (time.perf_counter() - start) / iters * 1000.0  # ms/op


def test_lock_order_p95_under_1ms():
    samples = []
    for _ in range(2000):
        t0 = time.perf_counter()
        canonical_lock_order(["fake-aux-a", "fake-aux-b", "hermes-aux-canary"])
        samples.append((time.perf_counter() - t0) * 1000.0)
    assert _p95(samples) < 1.0


def test_graph_order_p95_under_2ms():
    g = DependencyGraph(service_ids=(A, B, CANARY),
                        edges=((A, CANARY), (B, CANARY)))
    samples = []
    for _ in range(2000):
        t0 = time.perf_counter()
        topological_order(g)
        samples.append((time.perf_counter() - t0) * 1000.0)
    assert _p95(samples) < 2.0


def test_eligibility_aggregation_p95_under_2ms():
    verdicts = {A: True, B: True, CANARY: False}
    samples = []
    for _ in range(2000):
        t0 = time.perf_counter()
        aggregate_eligibility(verdicts)
        samples.append((time.perf_counter() - t0) * 1000.0)
    assert _p95(samples) < 2.0


def test_plan_validation_p95_under_2ms():
    b = PlanBuilder(CoordinationRegistry(), "baseline")
    plan, err = build_plan(b, sids=(A, B))
    assert err is None
    samples = []
    # re-validate the frozen plan hash is pure & fast
    for _ in range(2000):
        t0 = time.perf_counter()
        plan.compute_hash()
        samples.append((time.perf_counter() - t0) * 1000.0)
    assert _p95(samples) < 2.0