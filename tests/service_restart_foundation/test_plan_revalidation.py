"""Sprint 1.3.12 — immutable restart plan + binding + revalidation.

RestartPlan is immutable, bound to profile version/identity/graph/ports/health/
risk/blast/stop/start contracts/baseline/TTL. Drift -> REVALIDATE_REQUIRED.
"""
from __future__ import annotations

import pytest

from agent.service_restart_foundation.plan import (
    ServiceRestartPlan,
    build_restart_plan,
    revalidate_plan,
    PlanRevalidation,
)
from agent.service_restart_foundation.models import RestartProfile


def _profile(**kw) -> RestartProfile:
    base = dict(
        service_id="hermes-aux-canary", profile_version=1,
        unit_name="hermes-aux-canary.service", service_class="HERMES_AUXILIARY",
        criticality="LOW", restart_supported=True, expected_stop_timeout=10.0,
        expected_start_timeout=10.0, expected_old_pid_behavior="EXIT",
        expected_new_pid_behavior="NEW_PID_REQUIRED",
        expected_executable="/usr/bin/handler.py", expected_user="hermes",
        expected_ports=(), quiescence_policy="REQUIRE_FULL_QUIESCENCE",
        startup_contract_id="default", health_contract_id="default",
        rollback_strategy="RECONCILE_CURRENT_STATE", risk_class="HIGH",
        blast_radius_ceiling="SERVICE", restart_authority_enabled=False,
    )
    base.update(kw)
    return RestartProfile(**base)


def _plan(**kw):
    k = dict(
        plan_id="p1", transaction_id="tx1", service_id="hermes-aux-canary",
        profile_version=1, operation="RESTART", identity_fingerprint="fp",
        graph_digest="g1", old_pid_identity="old:100",
        expected_stop_contract="stop-c",
        quiescence_contract="q-c", expected_start_contract="start-c",
        health_contract="h-c", risk="HIGH", blast_radius="SERVICE",
        rollback_strategy="RECONCILE_CURRENT_STATE",
        recovery_strategy="RECONCILE_CURRENT_STATE",
        approval_required=True, created_at=0.0, expires_at=100.0,
        profile_version_bound=1, baseline_sha="baseline1",
        ports=("127.0.0.1:8080",),
    )
    k.update(kw)
    return ServiceRestartPlan(**k)


class TestRestartPlan:
    def test_immutable(self):
        p = _plan()
        with pytest.raises(Exception):
            p.plan_id = "x"

    def test_operation_is_restart(self):
        assert _plan().operation == "RESTART"

    def test_approval_required_by_default(self):
        assert _plan().approval_required is True

    def test_bound_fields_present(self):
        p = _plan()
        assert p.profile_version == 1
        assert p.identity_fingerprint == "fp"
        assert p.graph_digest == "g1"
        assert p.blast_radius == "SERVICE"
        assert p.baseline_sha == "baseline1"


class TestRevalidation:
    def test_no_drift_revalidates_ok(self):
        r = revalidate_plan(
            _plan(),
            current_profile_version=1, current_identity="fp",
            current_graph="g1", current_ports=("127.0.0.1:8080",),
            current_health_ok=True, now=5.0,
        )
        assert r == PlanRevalidation.VALID

    def test_profile_version_drift_requires_revalidate(self):
        assert revalidate_plan(_plan(), current_profile_version=2, current_identity="fp",
                               current_graph="g1", current_ports=(), current_health_ok=True,
                               now=5.0) == PlanRevalidation.REVALIDATE_REQUIRED

    def test_identity_drift(self):
        assert revalidate_plan(_plan(), current_profile_version=1, current_identity="fp2",
                               current_graph="g1", current_ports=(), current_health_ok=True,
                               now=5.0) == PlanRevalidation.REVALIDATE_REQUIRED

    def test_graph_drift(self):
        assert revalidate_plan(_plan(), current_profile_version=1, current_identity="fp",
                               current_graph="g2", current_ports=(), current_health_ok=True,
                               now=5.0) == PlanRevalidation.REVALIDATE_REQUIRED

    def test_expired_plan(self):
        assert revalidate_plan(_plan(expires_at=3.0), current_profile_version=1,
                               current_identity="fp", current_graph="g1", current_ports=(),
                               current_health_ok=True, now=10.0) == PlanRevalidation.EXPIRED


class TestBuildPlan:
    def test_build_produces_immutable_restart_plan(self):
        p = build_restart_plan(profile=_profile(), transaction_id="tx9")
        assert isinstance(p, ServiceRestartPlan)
        assert p.operation == "RESTART"
        assert p.approval_required is True