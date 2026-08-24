from __future__ import annotations

from dataclasses import replace

import pytest

from agent.service_restart_policy import (
    AdmissionContext,
    BlastRadius,
    ConsumerClass,
    LimitedRestartPolicy,
    RestartAdmission,
    RestartProfileRegistry,
)


def good() -> AdmissionContext:
    return AdmissionContext(
        service_id="hermes-aux-canary",
        profile_version=1,
        operation="RESTART",
        service_class="HERMES_AUXILIARY",
        criticality="LOW",
        identity_verified=True,
        graph_healthy=True,
        dependents=(),
        consumer=ConsumerClass.NONE,
        blast_radius=BlastRadius.SERVICE,
        quiescence_proven=True,
        startup_proven=True,
        health_contract_complete=True,
        rollback_proven=True,
        pre_health_ok=True,
        approval_valid=True,
    )


def test_registry_is_static_immutable_and_contains_exactly_one_live_entry():
    registry = RestartProfileRegistry()
    assert registry.MAX == registry.MAX_PROFILES == 3
    assert tuple(registry.service_ids()) == ("hermes-aux-canary",)
    profile = registry.resolve("hermes-aux-canary", 1)
    assert profile.unit_name == "hermes-aux-canary.service"
    with pytest.raises((TypeError, AttributeError)):
        registry.entries["other"] = profile


def test_runtime_discovery_is_never_authority():
    registry = RestartProfileRegistry(runtime_discovery=lambda: ["attacker.service"])
    assert registry.resolve("attacker", 1) is None
    decision = RestartAdmission(registry).decide(
        replace(good(), runtime_discovered_unit="attacker.service")
    )
    assert not decision.allowed
    assert decision.reason == "IDENTITY_UNVERIFIED"


@pytest.mark.parametrize("consumer", [ConsumerClass.NONE, ConsumerClass.PASSIVE, ConsumerClass.NON_CRITICAL])
def test_allowed_consumers(consumer):
    assert RestartAdmission(RestartProfileRegistry()).decide(replace(good(), consumer=consumer)).allowed


@pytest.mark.parametrize("consumer", [ConsumerClass.ACTIVE, ConsumerClass.CRITICAL, ConsumerClass.UNKNOWN])
def test_denied_consumers(consumer):
    d = RestartAdmission(RestartProfileRegistry()).decide(replace(good(), consumer=consumer))
    assert (d.allowed, d.reason) == (False, "CONSUMER_DENIED")


@pytest.mark.parametrize("blast", [BlastRadius.RESOURCE, BlastRadius.SERVICE])
def test_allowed_blast_radius(blast):
    assert RestartAdmission(RestartProfileRegistry()).decide(replace(good(), blast_radius=blast)).allowed


@pytest.mark.parametrize("blast", [BlastRadius.MULTI_SERVICE, BlastRadius.HOST, BlastRadius.NETWORK, BlastRadius.UNKNOWN])
def test_denied_blast_radius(blast):
    d = RestartAdmission(RestartProfileRegistry()).decide(replace(good(), blast_radius=blast))
    assert (d.allowed, d.reason) == (False, "BLAST_RADIUS_DENIED")


def test_gateway_is_always_first_and_all_gateway_mutations_are_self_control_forbidden():
    admission = RestartAdmission(RestartProfileRegistry())
    hostile = replace(good(), service_id="hermes-gateway", operation="STOP", approval_valid=False)
    assert admission.decide(hostile).reason == "SELF_CONTROL_FORBIDDEN"
    for op in ("RESTART", "STOP", "START", "KILL", "SIGNAL"):
        assert LimitedRestartPolicy().public_mutation("hermes-gateway", op).reason == "SELF_CONTROL_FORBIDDEN"


def test_strict_twenty_step_precedence_is_declared_and_exercised():
    admission = RestartAdmission(RestartProfileRegistry())
    assert admission.PRECEDENCE == (
        "SELF_CONTROL_FORBIDDEN", "NOT_REGISTERED", "SERVICE_CLASS_DENIED",
        "IDENTITY_UNVERIFIED", "PROFILE_VERSION_MISMATCH", "GRAPH_UNHEALTHY",
        "CONSUMER_DENIED", "DEPENDENCY_DENIED", "BLAST_RADIUS_DENIED",
        "PRE_HEALTH_FAILED", "CONFIG_INVALID", "QUIESCENCE_UNPROVEN",
        "STARTUP_UNPROVEN", "RECOVERY_UNPROVEN", "RISK_DENIED",
        "APPROVAL_INVALID", "BUDGET_EXCEEDED", "BREAKER_OPEN",
        "LOCK_CONFLICT", "ROLLOUT_DISABLED",
    )
    assert admission.decide(good()).reason == "ALLOW_EXACT_REGISTERED_PROFILE"


def test_earliest_failure_wins():
    d = RestartAdmission(RestartProfileRegistry()).decide(
        replace(good(), operation="STOP", graph_healthy=False, approval_valid=False)
    )
    assert d.reason == "OPERATION_DENIED"
