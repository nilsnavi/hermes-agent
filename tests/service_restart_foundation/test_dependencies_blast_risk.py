"""Sprint 1.3.12 — dependency quiescence + blast radius + risk monotonicity.

Restart not safe by service alone: named/critical dependents and shared resources
must be checked. If cascade risk -> blast MULTI_SERVICE -> deny. Restart risk must be
>= reload risk (never lower).
"""
from __future__ import annotations

from agent.service_restart_foundation.dependencies import (
    DependencyVerdict,
    evaluate_dependencies,
)
from agent.service_restart_foundation.blast_radius import (
    BlastVerdict,
    compute_blast_radius,
)
from agent.service_restart_foundation.risk import resolve_risk_class


class TestDependencyQuiescence:
    def test_no_dependents_ok(self):
        v = evaluate_dependencies(
            critical_dependents=(), active_dependents=(),
            shared_resources=(), bound_units=(),
            requires=(), wants=(), binds_to=(), part_of=(),
        )
        assert v.verdict == DependencyVerdict.SAFE

    def test_critical_dependent_denied(self):
        v = evaluate_dependencies(
            critical_dependents=("hermes-gateway",), active_dependents=(),
            shared_resources=(), bound_units=(),
            requires=(), wants=(), binds_to=(), part_of=(),
        )
        assert v.verdict == DependencyVerdict.DENY

    def test_active_dependent_denied(self):
        v = evaluate_dependencies(
            critical_dependents=(), active_dependents=("ui",),
            shared_resources=(), bound_units=(),
            requires=(), wants=(), binds_to=(), part_of=(),
        )
        assert v.verdict == DependencyVerdict.DENY

    def test_shared_resource_raises_risk(self):
        v = evaluate_dependencies(
            critical_dependents=(), active_dependents=(),
            shared_resources=("db-pool",), bound_units=(),
            requires=(), wants=(), binds_to=(), part_of=(),
        )
        assert v.verdict in (DependencyVerdict.DENY, DependencyVerdict.RAISE_RISK)

    def test_binds_to_part_of_denied(self):
        v = evaluate_dependencies(
            critical_dependents=(), active_dependents=(),
            shared_resources=(), bound_units=("consumer",),
            requires=(), wants=(), binds_to=("consumer",), part_of=(),
        )
        assert v.verdict == DependencyVerdict.DENY


class TestBlastRadius:
    def test_service_only_ok_when_no_dependents(self):
        assert compute_blast_radius(static_ceiling="SERVICE", critical_dependents=(),
                                    active_dependents=(),
                                    bound_units=(), shared_resources=()) == "SERVICE"

    def test_dependents_escalate_to_multiservice(self):
        assert compute_blast_radius(static_ceiling="SERVICE", critical_dependents=("x",),
                                    active_dependents=(),
                                    bound_units=(), shared_resources=()) == "MULTI_SERVICE"

    def test_bound_units_escalate(self):
        assert compute_blast_radius(static_ceiling="SERVICE", critical_dependents=(),
                                    active_dependents=(),
                                    bound_units=("b",), shared_resources=()) == "MULTI_SERVICE"

    def test_future_restart_requires_blast_le_service(self):
        assert compute_blast_radius(static_ceiling="SERVICE", critical_dependents=(),
                                    active_dependents=(),
                                    bound_units=(), shared_resources=()) == "SERVICE"


class TestRiskMonotonicity:
    def test_restart_risk_not_below_reload_risk(self):
        # reload = MEDIUM_MUTATION; restart must be >= MEDIUM (HIGH/CONFIG)
        assert resolve_risk_class("reload") in ("MEDIUM_MUTATION", "HIGH", "CRITICAL")
        assert resolve_risk_class("restart") in ("HIGH", "CRITICAL", "MEDIUM_MUTATION")
        order = {"MEDIUM_MUTATION": 1, "HIGH": 2, "CRITICAL": 3}
        assert order[resolve_risk_class("restart")] >= order[resolve_risk_class("reload")]

    def test_restart_strictly_above_when_reload_medium(self):
        # if reload is MEDIUM_MUTATION, profile cannot lower restart risk below it
        from agent.service_restart_foundation.risk import risk_not_below
        assert risk_not_below(profile_risk="LOW", reload_risk="MEDIUM_MUTATION") is False
        assert risk_not_below(profile_risk="HIGH", reload_risk="MEDIUM_MUTATION") is True