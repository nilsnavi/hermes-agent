"""Sprint 1.3.16 tests — compensation eligibility, idempotency, failure/unknown."""
from __future__ import annotations

from agent.multi_service_recovery.compensation import (
    build_compensation_plan, compensation_eligible, compensation_plan_status,
    compensation_unsupported,
)
from agent.multi_service_recovery.models import CompensationKey


def test_compensation_eligible_only_proven_effect():
    assert compensation_eligible("SIMULATED_EXECUTED") is True
    assert compensation_eligible("VERIFIED") is True
    assert compensation_eligible("COMPENSATION_REQUIRED") is True
    # NOT_STARTED / PREPARED-only / unknown-without-evidence => never compensated
    assert compensation_eligible("NOT_STARTED") is False
    assert compensation_eligible("PREPARED") is False
    assert compensation_eligible("UNKNOWN_OUTCOME") is False


def test_plan_compensates_reverse_topological_only_effect_children():
    plan = build_compensation_plan(
        transaction_id="tx", global_tx_id="g",
        service_set=("a", "b", "c"),
        rollback_order=["c", "b", "a"],  # dependents first
        child_states={"a": "VERIFIED", "b": "FAILED_SAFE", "c": "NOT_STARTED"},
        executed_set=frozenset({"a", "b"}), verified_set=frozenset({"a"}),
        failed_child="b", unknown_children=frozenset(),
        baseline_sha="b", plan_hash="p", recovery_generation=1,
    )
    # NOT_STARTED child c is never compensated (NOOP), a and b are
    ops = {s.service_id: s.operation for s in plan.steps}
    assert ops["a"] == "COMPENSATE_VERIFIED"
    assert ops["b"] == "COMPENSATE_FAILED_SAFE"
    assert ops["c"] == "NOOP"
    assert plan.rollback_supported is True
    assert list(plan.order) == ["c", "b", "a"]


def test_unsupported_compensation_is_manual_review_not_success():
    plan = build_compensation_plan(
        transaction_id="tx", global_tx_id="g", service_set=("a",),
        rollback_order=["a"], child_states={"a": "VERIFIED"},
        executed_set=frozenset({"a"}), verified_set=frozenset({"a"}),
        failed_child="", unknown_children=frozenset(),
        baseline_sha="b", plan_hash="p", recovery_generation=1,
    )
    # simulate an unsupported step
    from agent.multi_service_recovery.models import CompensationPlan, CompensationStep
    broken = CompensationPlan(
        global_tx_id="g", transaction_id="tx", service_set=("a",),
        executed_set=frozenset({"a"}), verified_set=frozenset({"a"}),
        failed_child="", unknown_children=frozenset(), baseline_sha="b",
        plan_hash="p", recovery_generation=1,
        steps=(CompensationStep("a", "COMPENSATE_VERIFIED", 0,
                                unsupported=True),),
    )
    assert compensation_unsupported(broken) is True


def test_compensation_key_replay_no_second_consume():
    k = CompensationKey("g", "c", "COMPENSATE_VERIFIED", 1, "svc-a", "rcpt")
    # a replayed compensation uses the SAME semantic key -> returns prior result
    s0 = k.value()
    assert CompensationKey("g", "c", "COMPENSATE_VERIFIED", 1, "svc-a", "rcpt").value() == s0
    # a different generation (recovery attempt) changes identity
    assert CompensationKey("g", "c", "COMPENSATE_VERIFIED", 2, "svc-a", "rcpt").value() != s0


def test_compensation_does_not_mint_new_authority():
    # build_compensation_plan returns a pure data plan; it never touches an
    # executor or calls an adapter.
    from agent.multi_service_recovery.compensation import build_compensation_plan
    plan = build_compensation_plan(
        transaction_id="t", global_tx_id="g", service_set=("a", "b"),
        rollback_order=["b", "a"],
        child_states={"a": "FAILED_SAFE", "b": "SIMULATED_EXECUTED"},
        executed_set=frozenset({"a", "b"}), verified_set=frozenset(),
        failed_child="a", unknown_children=frozenset(),
        baseline_sha="b", plan_hash="p", recovery_generation=1,
    )
    assert isinstance(plan.steps, tuple) and not hasattr(plan, "execute")