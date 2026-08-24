"""Sprint 1.3.16 tests — models, crash taxonomy, partial execution states."""
from __future__ import annotations

from agent.multi_service_recovery.models import (
    CompensationKey, CrashPoint, PartialState, RecoveryDisposition,
    RecoveryEvidence, RecoveryPlan,
)


def test_dispositions_are_exhaustive_and_include_unknown_fail_closed():
    names = {d.value for d in RecoveryDisposition}
    assert "UNKNOWN_RECOVERY_STATE" in names
    assert "MANUAL_REVIEW_REQUIRED" in names
    assert "SAFE_TO_ABORT" in names and "SAFE_TO_RESUME_PREPARE" in names
    assert "COMPENSATION_REQUIRED" in names and "TERMINAL" in names


def test_crash_taxonomy_covers_all_brief_points():
    names = {c.value for c in CrashPoint}
    for expected in ("AFTER_GLOBAL_CLAIM", "AFTER_BARRIER_READY",
                     "BEFORE_VERIFY", "AFTER_VERIFY_BEFORE_COMMIT",
                     "AFTER_SIMULATED_COMMIT", "DURING_COMPENSATION"):
        assert expected in names


def test_partial_state_never_jumps_to_committed_from_adapter_alone():
    # Committed must be a separate explicit terminal state, not an adapter
    # return.  There is NO partial state that implies committed on its own.
    names = {p.value for p in PartialState}
    assert "COMMITTED" not in names
    assert "SIMULATED_EXECUTED" in names
    assert "FAILED_SAFE" in names and "UNKNOWN_OUTCOME" in names


def test_recovery_evidence_is_immutable_and_versioned():
    ev = RecoveryEvidence(global_transaction_id="tx", semantic_key="k",
                          baseline_sha="b", plan_hash="p", graph_digest="g",
                          service_set_digest="a,b", evidence_version=1)
    try:
        from dataclasses import FrozenInstanceError
    except Exception:
        FrozenInstanceError = AttributeError
    import pytest
    with pytest.raises((FrozenInstanceError, AttributeError)):
        setattr(ev, "recovery_generation", 99)
    assert ev.evidence_version == 1
    assert ev.frozen() is ev


def test_compensation_key_is_semantic_and_replay_stable():
    import os
    k1 = CompensationKey("g", "c", "COMPENSATE_VERIFIED", 2, "svc-a", "rcpt").value()
    k2 = CompensationKey("g", "c", "COMPENSATE_VERIFIED", 2, "svc-a", "rcpt").value()
    assert k1 == k2
    k3 = CompensationKey("g", "c", "COMPENSATE_VERIFIED", 2, "svc-a", "rcpt-X").value()
    assert k1 != k3


def test_recovery_plan_is_immutable():
    import pytest
    p = RecoveryPlan(transaction_id="t", recovery_generation=1, global_tx_id="g",
                     semantic_key="k", disposition=RecoveryDisposition.TERMINAL,
                     crash_point="AFTER_SIMULATED_COMMIT")
    try:
        from dataclasses import FrozenInstanceError
    except Exception:
        FrozenInstanceError = AttributeError
    with pytest.raises((FrozenInstanceError, AttributeError)):
        setattr(p, "manual_review", True)