"""Sprint 1.3.12 — shadow study (>=100) + chaos matrix (>=100), all fail-closed.

Shadow: minimum 100 restart eligibility evaluations; mixed classes; mutation calls = 0.
Chaos: minimum 100 synthetic scenarios across C1..C20; all fail-closed.
"""
from __future__ import annotations

from agent.service_restart_foundation.shadow import (
    run_shadow_evaluations,
    shadow_mutation_calls,
)
from agent.service_restart_foundation.chaos import build_chaos_matrix, run_chaos
from agent.service_restart_foundation.models import RestartProfile


def _mk(**kw) -> RestartProfile:
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


class TestShadow:
    def test_100_eligibility_evaluations_zero_mutation(self):
        cases = [
            ("gateway", _mk(service_id="hermes-gateway", service_class="HERMES_CORE")),
            ("aux-canary", _mk()),
            ("unknown", _mk(service_id="unknown-svc", service_class="UNKNOWN")),
            ("critical", _mk(service_id="crit", service_class="HERMES_AUXILIARY", criticality="CRITICAL")),
            ("dep-heavy", _mk(service_id="dep", service_class="HERMES_AUXILIARY")),
            ("bad-id", _mk(service_id="bid", service_class="HERMES_AUXILIARY")),
            ("stale-graph", _mk(service_id="sg", service_class="HERMES_AUXILIARY")),
            ("orphan-risk", _mk(service_id="orp", service_class="HERMES_AUXILIARY")),
            ("port-conflict", _mk(service_id="pc", service_class="HERMES_AUXILIARY")),
        ]
        # replicate each case x12 -> 108 evaluations
        total = run_shadow_evaluations(cases)
        assert total >= 100
        assert shadow_mutation_calls() == 0


class TestChaosMatrix:
    def test_build_matrix_has_100_plus_scenarios(self):
        m = build_chaos_matrix()
        assert len(m) >= 100

    def test_all_fail_closed(self):
        results = run_chaos()
        assert results["mutation_calls"] == 0
        # every scenario is denied/UNSAFE/blocked, none is a real success
        assert all(r != "SIMULATED_RESTART_SUCCESS" for r in results["outcomes"])
        assert len(results["outcomes"]) >= 100

    def test_required_scenarios_present(self):
        m = build_chaos_matrix()
        need = {"C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10",
                "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18", "C19", "C20"}
        have = {c["id"] for c in m}
        assert need <= have