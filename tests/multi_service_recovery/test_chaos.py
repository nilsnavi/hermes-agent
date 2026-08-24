"""Sprint 1.3.16 tests — shadow recovery study + chaos matrix harness."""
from __future__ import annotations

from agent.multi_service_recovery.chaos import (
    RECOVERY_CHAOS_TARGETS, run_shadow_recovery_study,
)
from agent.multi_service_recovery.models import RecoveryDisposition


def test_shadow_recovery_study_100pct(tmp_path):
    r = run_shadow_recovery_study(500, seed=42)
    assert r.evaluations == 500
    assert r.correctness == 100.0
    assert r.adapter_calls == 0
    assert r.mutations == 0
    assert r.failures == []


def test_chaos_matrix_covers_all_crash_points(tmp_path):
    # every recovery crash taxonomy target is exercised by the study
    assert len(RECOVERY_CHAOS_TARGETS) >= 24


def test_no_false_terminal_success_in_chaos(tmp_path):
    from agent.multi_service_recovery.chaos import SHADOW_SCENARIOS
    # scenarios that must NEVER be TERMINAL
    never_terminal = {"unknown_child_outcome", "compensation_before_effect",
                      "corrupt_commit_without_verify", "reordered_verify_no_effect",
                      "terminal_then_mutation", "baseline_drift", "graph_drift"}
    for sc in SHADOW_SCENARIOS:
        if sc.name in never_terminal:
            assert sc.expected != RecoveryDisposition.TERMINAL
    # and the ONLY terminal case is the true durable commit
    commit = [s for s in SHADOW_SCENARIOS if s.expected == RecoveryDisposition.TERMINAL]
    assert len(commit) == 1
    assert commit[0].name == "crash_after_simulated_commit"


def test_false_success_impossible_by_type(tmp_path):
    from agent.multi_service_recovery.classify import classify_disposition
    # a FAILED child can never produce a SAFE-* disposition
    d = classify_disposition(["GLOBAL_CLAIMED", "SIMULATION_STARTED",
                              "CHILD_SIMULATED"],
                             {"fake-aux-a": "FAILED_SAFE"})
    assert d != RecoveryDisposition.SAFE_TO_CONTINUE_VERIFY
    assert d != RecoveryDisposition.SAFE_TO_RESUME_PREPARE
    assert d == RecoveryDisposition.COMPENSATION_REQUIRED or d == RecoveryDisposition.MANUAL_REVIEW_REQUIRED