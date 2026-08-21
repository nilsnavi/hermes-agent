"""Test rehearsal: >=160 scenarios, all fail-closed, violations=0."""
from agent.service_restart_canary.rehearsal import (build_rehearsal_scenarios, run_rehearsal,
                                                    rehearsal_ok)


def test_rehearsal_total_ge_160():
    sc = build_rehearsal_scenarios()
    assert len(sc) >= 160


def test_rehearsal_no_unsafe_success():
    sc = build_rehearsal_scenarios()
    for r in sc:
        # success category is the ONLY allowed success; deny/fail/unknown scenarios must not be success
        if r.category != "success" and r.outcome == "SIMULATED_RESTART_SUCCESS":
            assert False, f"{r.scenario} must not be success"
    assert True


def test_rehearsal_category_coverage():
    sc = build_rehearsal_scenarios()
    needed = {"success", "old_pid_survives", "orphan", "quiescence_fail", "start_timeout",
              "wrong_executable", "port_conflict", "health_fail", "duplicate", "concurrency",
              "unknown_outcome", "recovery"}
    cats = {c: sum(1 for r in sc if r.category == c) for c in needed}
    assert cats["success"] >= 50
    assert cats["old_pid_survives"] >= 20
    assert cats["orphan"] >= 20
    assert cats["duplicate"] >= 20
    assert cats["unknown_outcome"] >= 10
    assert cats["recovery"] >= 10


def test_run_rehearsal_ok():
    metrics = run_rehearsal()
    assert metrics["total_scenarios"] >= 160
    assert metrics["mutations"] == 0
    assert rehearsal_ok(metrics) is True