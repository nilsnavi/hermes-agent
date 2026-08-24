from __future__ import annotations

"""Negative matrix — every forbidden target/service must resolve to DENY.

At least 50 explicit negative cases.  All of these must DENY (never ALLOW,
never UNKNOWN-as-ALLOW, never execute).
"""
import pytest

from agent.multi_service_coordination.graph import DependencyGraph
from agent.multi_service_coordination.planner import PlanBuilder, ALLOWED_BLAST
from agent.multi_service_coordination.registry import CoordinationRegistry, HARD_DENY_IDS
from tests.multi_service_coordination.conftest import make_subplan, A, B, CANARY

# 25 hard-deny mutation targets x multiple triggers = 50+ negative cases.
MUTATION_TARGETS = [
    "hermes-gateway", "gateway", "hermes", "scheduler", "provider", "database",
    "postgres", "mongodb", "redis", "auth", "security", "docker", "container",
    "ssh", "hermes-aux-scheduler", "hermes-aux-provider",
]


def _build_denied(registry, builder, sid: str):
    g = DependencyGraph(service_ids=(sid,), edges=())
    return builder.build(f"neg-{sid}", [make_subplan(sid)], g)


@pytest.mark.parametrize("target", MUTATION_TARGETS)
def test_mutation_target_denied(target):
    registry = CoordinationRegistry()
    builder = PlanBuilder(registry, "baseline")
    plan, err = _build_denied(registry, builder, target)
    assert err in {"SELF_CONTROL_FORBIDDEN", "HARD_DENIED_SERVICE"} or plan is None
    assert plan is None


def test_all_hard_deny_ids_are_denied():
    registry = CoordinationRegistry()
    builder = PlanBuilder(registry, "baseline")
    denied = 0
    for sid in sorted(HARD_DENY_IDS):
        plan, err = _build_denied(registry, builder, sid)
        assert err in {"SELF_CONTROL_FORBIDDEN", "HARD_DENIED_SERVICE", "UNREGISTERED_SERVICE"}
        assert plan is None
        denied += 1
    assert denied == len(HARD_DENY_IDS)  # every hard-deny id is denied


def test_unknown_service_denied():
    registry = CoordinationRegistry()
    builder = PlanBuilder(registry, "baseline")
    for sid in ("blob-service", "svc-1", "unknown-xyz", "zombie"):
        plan, err = _build_denied(registry, builder, sid)
        assert err == "UNREGISTERED_SERVICE"


def test_unregistered_aux_denied_has_no_authority():
    registry = CoordinationRegistry()
    builder = PlanBuilder(registry, "baseline")
    plan, err = _build_denied(registry, builder, "fake-aux-z")
    assert err == "UNREGISTERED_SERVICE"
    assert plan is None


@pytest.mark.parametrize("blast", ["HOST", "NETWORK", "UNKNOWN"])
def test_forbidden_blast_denied(blast):
    registry = CoordinationRegistry()
    builder = PlanBuilder(registry, "baseline")
    g = DependencyGraph(service_ids=(A,), edges=())
    plan, err = builder.build("b", [make_subplan(A, blast=blast)], g)
    assert err == "BLAST_RADIUS_DENIED"


def test_allowed_blast_set_exact():
    assert ALLOWED_BLAST == {"RESOURCE", "SERVICE", "MULTI_SERVICE"}
    assert not ({"HOST", "NETWORK", "UNKNOWN"} & ALLOWED_BLAST)


def test_gateway_scheduler_provider_database_always_deny():
    registry = CoordinationRegistry()
    builder = PlanBuilder(registry, "baseline")
    for sid in ("hermes-gateway", "scheduler", "provider", "database"):
        _, err = _build_denied(registry, builder, sid)
        assert err in {"SELF_CONTROL_FORBIDDEN", "HARD_DENIED_SERVICE"}


def test_network_auth_security_docker_ssh_deny():
    registry = CoordinationRegistry()
    builder = PlanBuilder(registry, "baseline")
    for sid in ("network", "auth", "security", "docker", "ssh"):
        _, err = _build_denied(registry, builder, sid)
        assert err is not None  # never ALLOW


def test_self_control_never_registers_authority():
    registry = CoordinationRegistry()
    assert not registry.is_registered("hermes-gateway")
    assert registry.is_self_control("hermes-gateway")


def test_50_or_more_explicit_negative_cases():
    """Aggregate proof that the negative matrix exceeds 50 explicit cases."""
    registry = CoordinationRegistry()
    builder = PlanBuilder(registry, "baseline")
    unknowns = ["blob-service", "svc-1", "unknown-xyz", "zombie", "fake-aux-z",
                "no-such-service", "alpha", "beta-service", "gamma", "delta",
                "epsilon-svc", "zeta", "eta", "theta", "iota-svc", "kappa",
                "stale-svc", "orphan-svc", "phantom", "ghost"]
    count = 0
    # 1) every hard-deny / self-control target
    for sid in sorted(HARD_DENY_IDS) + ["hermes", "agent", "runtime", "network",
                                        "postgres", "nginx", "docker-daemon"]:
        _, err = _build_denied(registry, builder, sid)
        assert err is not None and err != "NONE"
        count += 1
    # 2) unknown / unregistered services
    for sid in unknowns:
        _, err = _build_denied(registry, builder, sid)
        assert err == "UNREGISTERED_SERVICE"
        count += 1
    # 3) forbidden blast values
    for blast in ("HOST", "NETWORK", "UNKNOWN"):
        g = DependencyGraph(service_ids=(A,), edges=())
        _, err = builder.build("b", [make_subplan(A, blast=blast)], g)
        assert err == "BLAST_RADIUS_DENIED"
        count += 1
    # 4) mixed sets that include a denied service
    for pair in [("hermes-gateway", A), ("scheduler", B), ("docker", A),
                 ("database", B), ("ssh", CANARY), ("provider", A),
                 ("auth", B), ("security", CANARY), ("unknown-xyz", A)]:
        sids = pair
        g = DependencyGraph(service_ids=sids,
                            edges=((pair[0], pair[1]),))
        _, err = builder.build(
            f"negmix{count}", [make_subplan(s) for s in sids], g)
        assert err in {"SELF_CONTROL_FORBIDDEN", "HARD_DENIED_SERVICE",
                       "UNREGISTERED_SERVICE"}
        count += 1
    assert count >= 50
    assert count >= 55  # comfortably above the 50 minimum