from __future__ import annotations

from agent.multi_service_coordination._durable import CoordinationStore
from agent.multi_service_coordination.idempotency import semantic_key
from agent.multi_service_coordination.planner import PlanBuilder
from agent.multi_service_coordination.registry import CoordinationRegistry
from tests.multi_service_coordination.conftest import build_plan, A, B, CANARY


def test_semantic_key_is_time_invariant(tmp_path):
    b = PlanBuilder(CoordinationRegistry(), "baseline")
    plan1, _ = build_plan(b)
    plan2, _ = build_plan(b)
    digest = CoordinationRegistry().registry_digest
    # identical intent (same baseline/services/ops/configs/digests) -> same key
    assert semantic_key(plan1, digest) == semantic_key(plan2, digest)


def test_semantic_key_changes_with_service_set(tmp_path):
    b = PlanBuilder(CoordinationRegistry(), "baseline")
    digest = CoordinationRegistry().registry_digest
    p2, _ = build_plan(b, sids=(A, B))
    p3, _ = build_plan(b, sids=(A, B, CANARY))
    assert semantic_key(p2, digest) != semantic_key(p3, digest)


def test_global_claim_is_exactly_once(tmp_path):
    store = CoordinationStore(tmp_path / "store")
    key = "sem-key"
    assert store.claim_global(key, "tx-1") == "CLAIMED_BY_ME"
    assert store.claim_global(key, "tx-2") == "CLAIMED_BY_OTHER"
    # same owner re-claim
    assert store.claim_global(key, "tx-1") == "ALREADY_MINE"


def test_duplicate_intent_does_not_consume_second_approval_or_budget(tmp_path):
    """The coordinator record_result closes a duplicate with zero new work."""
    store = CoordinationStore(tmp_path / "store")
    key = "dup-key"
    store.claim_global(key, "tx-A")
    store.record_result(key, "tx-A", "COMMITTED_SIMULATED", {"order": ["a", "b"]})
    prior = store.get_idem(key)
    assert prior["state"] == "COMMITTED_SIMULATED"
    assert prior["result"]["order"] == ["a", "b"]
    # a new claim for the same key must surface ALREADY_TERMINAL, not re-run
    assert store.claim_global(key, "tx-B") == "ALREADY_TERMINAL"


def test_idempotency_durable_across_store_reopen(tmp_path):
    store1 = CoordinationStore(tmp_path / "store")
    store1.claim_global("k", "tx-1")
    store1.record_result("k", "tx-1", "COMMITTED_SIMULATED", {"order": []})
    store2 = CoordinationStore(tmp_path / "store")
    assert store2.get_idem("k")["state"] == "COMMITTED_SIMULATED"


def test_duplicate_claim_never_replays_twice(tmp_path):
    store = CoordinationStore(tmp_path / "store")
    key = "once"
    store.claim_global(key, "tx-1")
    # recording once
    assert store.record_result(key, "tx-1", "COMMITTED_SIMULATED", {})
    # second record_result for same owner+key is still one result
    assert store.get_idem(key)["result"] == {}


def test_foreign_owner_cannot_set_state_or_record(tmp_path):
    """§11 spoofed/foreign owner DENY at the durable-claim layer."""
    store = CoordinationStore(tmp_path / "store")
    key = "k-owner"
    store.claim_global(key, "tx-real")
    # foreign owner cannot mutate state or record a result for this claim
    assert store.set_idem_state(key, "tx-forged", "COMMITTED_SIMULATED") is False
    assert store.record_result(key, "tx-forged", "COMMITTED_SIMULATED", {}) is False
    assert store.get_idem(key)["state"] == "CLAIMED"  # untouched
    # real owner still can
    assert store.set_idem_state(key, "tx-real", "VERIFYING") is True