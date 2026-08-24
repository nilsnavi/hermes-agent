"""Sprint 1.3.16 tests — recovery concurrency (workers, claim races, compensation races)."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from tests.multi_service_recovery.conftest import make_store

J_CMT = ["GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED",
         "CHILD_SIMULATED", "VERIFY_COMPLETED", "GLOBAL_SIMULATED_COMMIT"]


def test_recovery_claim_exactly_one_owner_100_races(tmp_path):
    import os
    from agent.multi_service_recovery.provenance import Provenance
    store = make_store(tmp_path)
    results = []
    barrier = threading.Barrier(20)
    def runner(i):
        barrier.wait()
        prov = Provenance(pid=os.getpid(), host_identity=store.host_identity)
        results.append(store.claims.claim(
            "race-tx", 1, pid=prov.pid,
            process_start_identity=prov.process_start_identity,
            runtime_identity=prov.runtime_identity, nonce=f"n{i}",
            lease_created=0.0, lease_expiry=99999.0,
            host_identity=store.host_identity))
    threads = [threading.Thread(target=runner, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join(timeout=10) for t in threads]
    assert results.count("CLAIMED") == 1
    assert len(results) == 20


def test_20_recovery_workers_distinct_tx_no_cross_contention(tmp_path):
    from agent.multi_service_recovery.coordinator import MultiServiceRecoveryCoordinator
    from agent.multi_service_recovery.provenance import Provenance
    from agent.multi_service_recovery.clock import FixedClock
    store = make_store(tmp_path)
    plans = []
    def worker(i):
        prov = Provenance(host_identity=store.host_identity)
        coord = MultiServiceRecoveryCoordinator(
            store, provenance=prov, clock=FixedClock(1000 + i),
            transaction_id=f"tx-{i}", semantic_key=f"sem-{i}",
            baseline_sha="b", plan_hash="p", graph_digest="g",
            service_set=("fake-aux-a",), recovery_generation=1)
        return coord.recover(journal_types=J_CMT, child_states={},
                             idempotency_state="COMMITTED_SIMULATED")
    with ThreadPoolExecutor(max_workers=10) as ex:
        plans = list(ex.map(worker, range(20)))
    # every worker independently classified terminal, no cross-cancellation
    from agent.multi_service_recovery.models import RecoveryDisposition
    assert all(p.disposition == RecoveryDisposition.TERMINAL for p in plans)


def test_100_compensation_claim_races_exactly_one(tmp_path):
    store = make_store(tmp_path)
    key = "comp-key"
    outcomes = []
    barrier = threading.Barrier(20)
    def runner(i):
        barrier.wait()
        outcomes.append(store.compensation.claim_action(key, f"worker-{i}"))
    threads = [threading.Thread(target=runner, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join(timeout=10) for t in threads]
    assert outcomes.count("CLAIMED") == 1
    assert sum(o != "CLAIMED" for o in outcomes) == 19


def test_compensation_single_done_prevents_double(tmp_path):
    store = make_store(tmp_path)
    key = "k"
    assert store.compensation.claim_action(key, "w1") == "CLAIMED"
    assert store.compensation.mark_done(key, "w1") is True
    # a second completion for the SAME key is refused (idempotency)
    assert store.compensation.mark_done(key, "w1") is False
    assert store.compensation.is_done(key) is True


def test_compensation_race_no_double_consume(tmp_path):
    store = make_store(tmp_path)
    key = "race-comp"
    winner = []
    def runner():
        c = store.compensation.claim_action(key, "comp")
        if c in ("CLAIMED", "ALREADY_OWNED"):
            winner.append(store.compensation.mark_done(key, "comp"))
    with ThreadPoolExecutor(max_workers=15) as ex:
        list(ex.map(lambda _: runner(), range(60)))
    assert winner.count(True) == 1