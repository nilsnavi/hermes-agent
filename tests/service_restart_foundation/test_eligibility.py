"""Sprint 1.3.12 — restart eligibility (test_eligibility.py).

Strict fail-closed precedence: self-control FIRST, then class/identity/graph/
blast/criticality/stop/quiescence/orphan/start/executable/ports/health/rollback/risk.
ELIGIBLE_FOR_FUTURE_RESTART_CANARY is NOT execution authority.
"""
from __future__ import annotations

from agent.service_restart_foundation.eligibility import (
    evaluate_eligibility,
    EligibilityReason,
)
from agent.service_restart_foundation.models import RestartProfile


def _profile(**kw) -> RestartProfile:
    base = dict(
        service_id="hermes-aux-canary",
        profile_version=1,
        unit_name="hermes-aux-canary.service",
        service_class="HERMES_AUXILIARY",
        criticality="LOW",
        restart_supported=True,
        expected_stop_timeout=10.0,
        expected_start_timeout=10.0,
        expected_old_pid_behavior="EXIT",
        expected_new_pid_behavior="NEW_PID_REQUIRED",
        expected_executable="/usr/bin/handler.py",
        expected_user="hermes",
        expected_ports=(),
        quiescence_policy="REQUIRE_FULL_QUIESCENCE",
        startup_contract_id="default",
        health_contract_id="default",
        rollback_strategy="RECONCILE_CURRENT_STATE",
        risk_class="HIGH",
        blast_radius_ceiling="SERVICE",
        restart_authority_enabled=False,
    )
    base.update(kw)
    return RestartProfile(**base)


class _Ctx:
    def __init__(self, **kw):
        self.kw = dict(
            identity_verified=True,
            graph_status="HEALTHY",
            critical_dependents=0,
            active_dependents=0,
            blast_radius="SERVICE",
            criticality="LOW",
            stop_contract_known=True,
            quiescence_proven=True,
            orphan_risk=False,
            start_contract_known=True,
            executable_verified=True,
            port_transition_proven=True,
            health_pass=True,
            rollback_proven=True,
            risk_class="HIGH",
            restart_rollback_proven=True,
        )
        self.kw.update(kw)


def _ok_profile():
    return _profile()


def _ok_ctx():
    return _Ctx()


class TestSelfControl:
    def test_self_control_always_blocks(self):
        # gateway / runtime / self-control service -> SELF_CONTROL_FORBIDDEN even if identity VERIFIED
        prof = _profile(service_class="HERMES_CORE")
        assert evaluate_eligibility(prof, _Ctx().kw) == EligibilityReason.SELF_CONTROL_FORBIDDEN

    def test_self_control_precedes_identity(self):
        prof = _profile(service_class="HERMES_CORE")
        ctx = _Ctx(identity_verified=False).kw
        # even with bad identity, self-control is the reason (precedence #1)
        assert evaluate_eligibility(prof, ctx) == EligibilityReason.SELF_CONTROL_FORBIDDEN


class TestEligibilityOrder:
    def test_happy_path_future_canary(self):
        assert evaluate_eligibility(_ok_profile(), _ok_ctx().kw) == \
            EligibilityReason.ELIGIBLE_FOR_FUTURE_RESTART_CANARY

    def test_class_denied(self):
        prof = _profile(service_class="DATASTORE")
        assert evaluate_eligibility(prof, _ok_ctx().kw) == EligibilityReason.SERVICE_CLASS_DENIED

    def test_identity_unverified(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(identity_verified=False).kw) == \
            EligibilityReason.IDENTITY_UNVERIFIED

    def test_graph_stale(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(graph_status="STALE").kw) == \
            EligibilityReason.GRAPH_UNHEALTHY

    def test_blast_too_high(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(blast_radius="MULTI_SERVICE").kw) == \
            EligibilityReason.BLAST_TOO_HIGH

    def test_critical_dependents(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(critical_dependents=2).kw) == \
            EligibilityReason.DEPENDENCY_RISK

    def test_stop_contract_missing(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(stop_contract_known=False).kw) == \
            EligibilityReason.STOP_CONTRACT_MISSING

    def test_quiescence_unproven(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(quiescence_proven=False).kw) == \
            EligibilityReason.QUIESCENCE_UNPROVEN

    def test_orphan_risk(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(orphan_risk=True).kw) == \
            EligibilityReason.ORPHAN_RISK

    def test_start_contract_missing(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(start_contract_known=False).kw) == \
            EligibilityReason.START_CONTRACT_MISSING

    def test_executable_mismatch(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(executable_verified=False).kw) == \
            EligibilityReason.IDENTITY_UNVERIFIED

    def test_port_transition_unproven(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(port_transition_proven=False).kw) == \
            EligibilityReason.PORT_TRANSITION_UNPROVEN

    def test_health_missing(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(health_pass=False).kw) == \
            EligibilityReason.HEALTH_CONTRACT_MISSING

    def test_rollback_unproven(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(rollback_proven=False).kw) == \
            EligibilityReason.ROLLBACK_UNPROVEN

    def test_restart_rollback_unproven(self):
        assert evaluate_eligibility(_ok_profile(), _Ctx(restart_rollback_proven=False).kw) == \
            EligibilityReason.ROLLBACK_UNPROVEN

    def test_risk_too_low_denied(self):
        # restart baseline risk must be >= reload risk; a LOW profile is suspicious
        assert evaluate_eligibility(_profile(risk_class="LOW"), _ok_ctx().kw) == \
            EligibilityReason.RISK_TOO_LOW


class TestEligibilityNotAuthority:
    def test_eligible_is_not_execution_authority(self):
        # eligibility alone must NOT allow execution; execution guard is separate
        from agent.service_restart_foundation.guard import restart_execution_guard, adapter_calls
        out = restart_execution_guard(plan_id="p", service_id="hermes-aux-canary")
        assert out == "SERVICE_RESTART_DISABLED"
        # no adapter call is ever allowed, regardless of eligibility
        assert adapter_calls() == 0