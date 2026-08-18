from agent.sandbox_runtime.reconciliation import ReconciliationOutcome, reconcile_state


def test_reconciliation_outcomes_are_read_only_and_exact():
    assert reconcile_state("before", "after", "before") is ReconciliationOutcome.UNCHANGED
    assert reconcile_state("before", "after", "after") is ReconciliationOutcome.APPLIED
    assert reconcile_state("before", "after", "aft") is ReconciliationOutcome.PARTIALLY_APPLIED
    assert reconcile_state("before", "after", "other") is ReconciliationOutcome.DIVERGED
    assert reconcile_state("before", "after", None) is ReconciliationOutcome.UNKNOWN
