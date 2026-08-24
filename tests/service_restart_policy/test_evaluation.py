from __future__ import annotations

from agent.service_restart_policy.evaluation import REHEARSAL_TARGETS, run_rehearsal, run_shadow_study


def test_shadow_study_has_at_least_100_evaluations_zero_mutations_and_100_correctness(tmp_path):
    report = run_shadow_study(tmp_path, evaluations=120)
    assert report.evaluations >= 100
    assert report.mutations == 0
    assert report.correct == report.evaluations
    assert report.correctness == 100.0
    assert report.subprocess_calls == 0


def test_rehearsal_exact_scenario_counts_and_zero_violations(tmp_path):
    report = run_rehearsal(tmp_path)
    assert report.counts == REHEARSAL_TARGETS == {
        "success": 50,
        "duplicate": 20,
        "concurrent": 20,
        "stale_lock": 20,
        "pid_reuse": 20,
        "orphan": 20,
        "consumer_critical": 20,
        "graph_drift": 20,
        "health_fail": 20,
        "unknown": 10,
        "breaker": 10,
        "budget": 10,
    }
    assert report.violations == 0
    assert report.real_mutations == 0
    # Expired-but-live owner scenarios are now denied before the adapter (20 calls removed).
    assert report.fake_subprocess_calls == 180


def test_rehearsal_total_matches_all_required_scenarios(tmp_path):
    report = run_rehearsal(tmp_path)
    assert report.total == 240
