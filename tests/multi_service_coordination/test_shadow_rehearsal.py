from __future__ import annotations

"""Shadow study (500) + rehearsal (500) acceptance — 100% correctness / 0 mutation / 0 adapter."""
from agent.multi_service_coordination.evaluation import (
    run_rehearsal,
    run_shadow_study,
    REHEARSAL_TARGET_SCENARIOS,
    SHADOW_CASE_FAMILIES,
)


def test_shadow_study_500_100pct_correct_zero_mutation(tmp_path):
    report = run_shadow_study(tmp_path, evaluations=500)
    assert report.evaluations == 500
    assert report.correctness == 100.0
    assert report.mutations == 0
    assert report.adapter_calls == 0
    assert report.failures == []
    # every required family was exercised
    for fam in SHADOW_CASE_FAMILIES:
        assert report.case_counts.get(fam, 0) > 0, fam


def test_rehearsal_500_zero_violations_zero_mutation(tmp_path):
    report = run_rehearsal(tmp_path, scenarios=500)
    assert report.total == 500
    assert report.violations == 0
    assert report.real_mutations == 0
    assert report.adapter_calls == 0
    for name in REHEARSAL_TARGET_SCENARIOS:
        assert name in report.counts, name


def test_shadow_never_touches_production_budget(tmp_path):
    report = run_shadow_study(tmp_path, evaluations=500)
    # simulation does not consume a production success budget
    assert report.mutations == 0