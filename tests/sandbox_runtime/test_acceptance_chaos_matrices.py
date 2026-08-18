"""Deterministic acceptance matrices for sandbox chaos gaps 3/4/5/6/8/9."""
from __future__ import annotations

import os

import pytest

from agent.sandbox_runtime.chaos_drills import (
    PARTIAL_MUTATION_CASES,
    PROCESS_DEATH_CASES,
    ROLLBACK_FAILURE_CASES,
    TIMEOUT_PHASES,
    run_concurrency_matrix,
    run_partial_mutation_case,
    run_process_death_case,
    run_rollback_failure_case,
    run_service_chaos_matrix,
    run_timeout_case,
)


@pytest.mark.parametrize("case", PROCESS_DEATH_CASES, ids=lambda case: case.case_id)
def test_c1_c10_child_death_has_distinct_durable_boundary_and_no_success(tmp_path, case):
    result = run_process_death_case(str(tmp_path), case)

    assert result.returncode == case.exit_code
    assert result.observed_phases == case.expected_durable_phases
    assert result.resource_state == case.expected_resource_state
    assert result.classification in {
        "NOT_APPLIED", "UNKNOWN_OUTCOME", "APPLIED_UNCOMMITTED",
        "ROLLBACK_UNCOMMITTED",
    }
    assert result.classification != "COMMITTED"
    assert result.auto_retry is False
    assert not os.path.exists(result.success_marker)


def test_c1_c10_are_ten_distinct_phase_and_resource_boundaries():
    assert len(PROCESS_DEATH_CASES) == 10
    assert len({case.phase for case in PROCESS_DEATH_CASES}) == 10
    assert len({case.boundary_action for case in PROCESS_DEATH_CASES}) == 10


@pytest.mark.parametrize("case", PARTIAL_MUTATION_CASES, ids=lambda case: case.case_id)
def test_nine_partial_mutations_are_observed_then_really_rolled_back(sandbox_root, case):
    result = run_partial_mutation_case(sandbox_root, case)

    assert case.fault_adapter in {
        "partial-temp-write", "missing-fsync", "missing-rename",
        "rename-complete-commit-missing", "original-unexpectedly-removed",
        "content-corrupted", "partial-chmod", "parent-changed",
        "inode-replaced",
    }
    # Some crash-safe cases intentionally leave the original intact (before),
    # while post-rename crashes may expose the exact after-state.  Neither is
    # silently committed; every case is reconciled and rolled back below.
    assert result.intermediate_digest
    assert result.rollback.status == "ROLLED_BACK"
    assert result.rollback.manual_review_required is False
    assert result.final_digest == result.before_digest
    assert result.artifacts_remaining == ()


def test_concurrency_acceptance_matrix_uses_real_full_writers_and_conflicts(tmp_path):
    result = run_concurrency_matrix(str(tmp_path))

    assert result.duplicate_requests == 50
    assert result.duplicate_executions == 1
    assert result.same_resource_writers == 20
    assert result.same_resource_max_active == 1
    assert result.same_resource_complete_writes == 20
    assert result.different_resource_writers == 20
    assert result.different_resource_max_active >= 2
    assert result.races == {
        "writer-vs-rollback": "SERIALIZED",
        "verify-vs-writer": "STALE_VERIFY_REJECTED",
        "delete-vs-write": "SERIALIZED",
        "rename-vs-chmod": "SERIALIZED",
    }
    assert result.dangling_locks == ()


@pytest.mark.parametrize("case", ROLLBACK_FAILURE_CASES, ids=lambda case: case.case_id)
def test_r1_r10_use_rollback_manager_fault_adapters_and_preserve_both_errors(sandbox_root, case):
    result = run_rollback_failure_case(sandbox_root, case)

    assert result.outcome.status == "ROLLBACK_VERIFY_FAILED"
    assert result.outcome.manual_review_required is True
    assert result.outcome.original_failure == "primary mutation failed"
    assert result.outcome.audit["original_failure"] == "primary mutation failed"
    assert case.error_text in result.outcome.audit["rollback_error"]
    assert result.observed_state != b"BEFORE"


@pytest.mark.parametrize("phase", TIMEOUT_PHASES)
def test_seven_phase_timeouts_reap_worker_release_lock_and_allow_explicit_retry(tmp_path, phase):
    result = run_timeout_case(str(tmp_path), phase, timeout_s=0.15)

    assert result.timed_out is True
    assert result.elapsed_s < 2.0
    assert result.worker_alive is False
    assert result.dangling_lock is False
    assert result.false_commit is False
    assert result.auto_retry_count == 0
    assert result.explicit_retry_count == 1
    assert result.retry_status == "COMMITTED"


def test_service_chaos_matrix_blocks_reused_identity_and_reaps_process_group(sandbox_root):
    result = run_service_chaos_matrix(sandbox_root)

    assert result.pid_reuse_blocked is True
    assert result.unrelated_process_survived is True
    assert result.identity_drift_blocked is True
    assert result.process_group_reaped is True
    assert result.health_timed_out is True
    assert result.health_elapsed_s < 1.0
    assert result.production_identity_blocked is True
