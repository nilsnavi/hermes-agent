from __future__ import annotations

from agent.multi_service_coordination.graph import (
    DependencyGraph,
    rollback_order,
    topological_order,
    validate_desired_order,
)
from agent.multi_service_coordination.registry import CoordinationRegistry

R = CoordinationRegistry()


def _g(sids, edges=()):
    return DependencyGraph(service_ids=tuple(sids), edges=tuple(edges))


def test_linear_chain_order():
    g = _g(("fake-aux-b", "fake-aux-a"), (("fake-aux-a", "fake-aux-b"),))
    assert topological_order(g) == ["fake-aux-b", "fake-aux-a"]  # dep first


def test_diamond_order_depends_before_dependents():
    g = _g(("fake-aux-a", "fake-aux-b", "hermes-aux-canary"),
           (("fake-aux-a", "hermes-aux-canary"), ("fake-aux-b", "hermes-aux-canary")))
    topo = topological_order(g)
    assert topo is not None
    # canary is a dependency of both A and B -> must come first
    assert topo.index("hermes-aux-canary") < topo.index("fake-aux-a")
    assert topo.index("hermes-aux-canary") < topo.index("fake-aux-b")


def test_rollback_is_reverse_topological_not_reverse_input():
    g = _g(("fake-aux-a", "fake-aux-b"), (("fake-aux-b", "fake-aux-a"),))
    # A depends on B => execution B then A => rollback A then B
    topo = topological_order(g)
    assert topo == ["fake-aux-a", "fake-aux-b"]
    assert rollback_order(g, topo) == ["fake-aux-b", "fake-aux-a"]


def test_cycle_is_detected_and_order_returns_none():
    g = _g(("fake-aux-a", "fake-aux-b"),
           (("fake-aux-a", "fake-aux-b"), ("fake-aux-b", "fake-aux-a")))
    assert g.validated(R).status.value == "CYCLE"
    assert topological_order(g) is None


def test_unknown_dependency_fails_closed():
    g = _g(("fake-aux-a",), (("fake-aux-a", "ghost"),))
    assert g.validated(R).status.value == "UNKNOWN_DEPENDENCY"


def test_corrupt_duplicate_service_ids():
    g = _g(("fake-aux-a", "fake-aux-a"))
    assert g.validated(R).status.value == "CORRUPT"


def test_too_large_bounds():
    g = _g(("a1", "a2", "a3", "a4", "a5"))
    assert g.validated(R).status.value == "TOO_LARGE"
    big = _g(("fake-aux-a", "fake-aux-b", "fake-aux-c"))
    edges = tuple((f"fake-aux-{i}", f"fake-aux-{j}") for i in range(4) for j in range(4))
    g2 = DependencyGraph(("fake-aux-a", "fake-aux-b", "fake-aux-c", "d4"),
                         edges=edges)
    assert g2.validated(R).status.value == "UNKNOWN_DEPENDENCY" or g2.validated(R).status.value == "TOO_LARGE"


def test_callers_desired_order_is_validated_not_authoritative():
    g = _g(("fake-aux-a", "fake-aux-b"), (("fake-aux-a", "fake-aux-b"),))
    # B is a dependency of A -> desired [A, B] violates the graph
    assert validate_desired_order(g, ["fake-aux-a", "fake-aux-b"]) == "PLAN_INVALID"
    assert validate_desired_order(g, ["fake-aux-b", "fake-aux-a"]) is None


def test_desired_order_rejects_mismatched_service_set():
    g = _g(("fake-aux-a", "fake-aux-b"), ())
    assert validate_desired_order(g, ["fake-aux-a"]) == "PLAN_INVALID"


def test_graph_digest_is_stable_and_meaningful():
    g = _g(("fake-aux-a", "fake-aux-b"), (("fake-aux-a", "fake-aux-b"),))
    assert g.compute_digest() == _g(("fake-aux-a", "fake-aux-b"),
                                    (("fake-aux-a", "fake-aux-b"),)).compute_digest()
    assert g.compute_digest() != _g(("fake-aux-b", "fake-aux-a"),
                                    (("fake-aux-a", "fake-aux-b"),)).compute_digest()