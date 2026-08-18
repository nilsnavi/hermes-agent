"""Sprint 1.3.9 — self-control P0, execution guard, classes, identity."""
from __future__ import annotations

import pytest

from agent.service_foundation import (Eligibility, IdentityResult, Operation, ServiceClass,
                                      build_default_profiles, evaluate, execute,
                                      plan_fingerprint, revalidate_required, verify_identity)
from agent.service_foundation.exceptions import ExecutionDisabled
from agent.service_foundation.graph import ServiceDependencyGraph
from agent.service_foundation.models import ServiceChangePlan
from agent.service_foundation.registry import ServiceRegistry


def _verdict(profile, identity, op, **kw):
    g = ServiceDependencyGraph(partial=False)
    base = dict(health_ok=True, validator_ok=True, rollback_proven=True)
    base.update(kw)
    return evaluate(profile, identity, g, op, **base)


def test_execute_always_disabled():
    with pytest.raises(ExecutionDisabled) as ei:
        execute(None)
    assert "SERVICE_MUTATION_DISABLED" in str(ei.value)


def test_gateway_self_control_forbidden():
    r = ServiceRegistry()
    p = r.get("hermes-gateway")
    assert p.self_control_class.value == "self_control_forbidden"
    # even identity VERIFIED + supported reload -> SELF_CONTROL_FORBIDDEN
    v = _verdict(p, IdentityResult.VERIFIED, Operation.RELOAD_ELIGIBILITY)
    assert v is Eligibility.SELF_CONTROL_FORBIDDEN
    v2 = _verdict(p, IdentityResult.VERIFIED, Operation.RESTART_ELIGIBILITY)
    assert v2 is Eligibility.SELF_CONTROL_FORBIDDEN


def test_self_control_win_before_everything():
    r = ServiceRegistry()
    p = r.get("hermes-gateway")
    # even identity mismatch / unhealthy graph -> blocked by self-control first
    v = _verdict(p, IdentityResult.MISMATCH, Operation.RELOAD_ELIGIBILITY, health_ok=False)
    assert v is Eligibility.SELF_CONTROL_FORBIDDEN


def test_aux_identity_required():
    r = ServiceRegistry()
    p = r.get("hermes-aux-agent")
    assert _verdict(p, IdentityResult.MISMATCH, Operation.RELOAD_ELIGIBILITY) is Eligibility.IDENTITY_UNVERIFIED
    assert _verdict(p, IdentityResult.PARTIAL, Operation.RELOAD_ELIGIBILITY) is Eligibility.IDENTITY_UNVERIFIED


def test_aux_future_reload_eligible_when_verified():
    r = ServiceRegistry()
    p = r.get("hermes-aux-agent")
    v = _verdict(p, IdentityResult.VERIFIED, Operation.RELOAD_ELIGIBILITY)
    assert v is Eligibility.ELIGIBLE_FOR_FUTURE_RELOAD_CANARY


def test_aux_future_restart_eligible_when_verified():
    r = ServiceRegistry()
    p = r.get("hermes-aux-agent")
    v = _verdict(p, IdentityResult.VERIFIED, Operation.RESTART_ELIGIBILITY)
    assert v is Eligibility.ELIGIBLE_FOR_FUTURE_RESTART_CANARY


def test_class_hard_deny():
    r = ServiceRegistry()
    p = r.get("hermes-gateway")  # HERMES_CORE
    assert _verdict(p, IdentityResult.VERIFIED, Operation.STATUS) is Eligibility.SELF_CONTROL_FORBIDDEN


def test_unknown_class_future_denied():
    from agent.service_foundation.models import (BlastRadius, Criticality, RiskClass,
                                                 SelfControlClass, ServiceProfile)
    from agent.service_foundation.registry import AUX
    p = ServiceProfile("x-unknown", 1, "x.service", service_class=ServiceClass.UNKNOWN,
                       criticality=Criticality.LOW, self_control_class=SelfControlClass.NORMAL,
                       reload_supported=True, restart_supported=True,
                       rollback_strategy="restore_config_and_reload",
                       risk_class=RiskClass.LOW, blast_radius_ceiling=BlastRadius.SERVICE,
                       health_contract_id="hc", config_validator_id="cv")
    v = _verdict(p, IdentityResult.VERIFIED, Operation.RELOAD_ELIGIBILITY)
    assert v is Eligibility.SERVICE_CLASS_DENIED


def test_identity_verified_checks():
    r = ServiceRegistry()
    p = r.get("hermes-aux-agent")
    assert verify_identity(p, {"unit_name": "hermes-aux-agent.service",
                               "executable": "/usr/local/bin/hermes-aux"}) is IdentityResult.VERIFIED
    assert verify_identity(p, {"unit_name": "hermes-aux-agent.service"}) is IdentityResult.PARTIAL
    assert verify_identity(p, {"unit_name": "wrong.service", "executable": "/usr/local/bin/x"}) is IdentityResult.MISMATCH
    assert verify_identity(p, {}) is IdentityResult.UNKNOWN


def test_revalidation():
    from agent.service_foundation.models import (BlastRadius, Operation, RiskClass,
                                                 ServiceChangePlan)
    a = ServiceChangePlan("p1", "s", 1, Operation.EXEC_RELOAD, "id1", "g1", "hc", "cv",
                          RiskClass.LOW, BlastRadius.SERVICE, True, "restore_config_and_reload",
                          "pre", "post", 0.0, 0.0)
    b = ServiceChangePlan("p2", "s", 1, Operation.EXEC_RELOAD, "id1", "G2", "hc", "cv",
                          RiskClass.LOW, BlastRadius.SERVICE, True, "restore_config_and_reload",
                          "pre", "post", 0.0, 0.0)
    assert revalidate_required(a, b) is True
    assert plan_fingerprint(a)
