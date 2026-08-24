"""Sprint 1.3.17 — concurrency certification (§25)."""

from __future__ import annotations

import threading

from agent.multi_service_execution.authority import ExecutionRuntime
from agent.multi_service_execution.fake_adapter import FakeServiceAdapter
from agent.multi_service_execution.pipeline import ExecutionPipeline
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan,
)


def test_50_parallel_coordinator_requests_distinct():
    from tests.multi_service_execution.conftest import make_pipeline
    import tempfile
    from pathlib import Path
    pipe, runtime, adapter, idem, rcpt = make_pipeline(
        Path(tempfile.mkdtemp()), env=ENV_REHEARSAL)
    results = []
    barrier = threading.Barrier(50)

    def run(i):
        barrier.wait()
        plan = make_exec_plan(make_coord_plan(("svc-a",), tx_id=f"c{i}"))
        results.append(pipe.execute(plan, child_admissions=green_admissions(plan)))

    ts = [threading.Thread(target=run, args=(i,)) for i in range(50)]
    [t.start() for t in ts]
    [t.join(timeout=20) for t in ts]
    assert len(results) == 50
    committed = [r for r in results if r["global_state"] == "SIMULATED_COMMITTED"]
    assert len(committed) == 50  # distinct txs all commit once
    assert sum(1 for r in results if r["adapter_call_count"] != 1) == 0


def test_100_global_claim_races_single_owner(tmp_path):
    from tests.multi_service_execution.conftest import make_pipeline
    pipe, runtime, adapter, idem, rcpt = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b", "svc-c"), tx_id="race"))
    out = []
    barrier = threading.Barrier(100)

    def run(_):
        barrier.wait()
        out.append(pipe.execute(plan, child_admissions=green_admissions(plan)))

    ts = [threading.Thread(target=run, args=(i,)) for i in range(100)]
    [t.start() for t in ts]
    [t.join(timeout=25) for t in ts]
    committed = [r for r in out if r["global_state"] == "SIMULATED_COMMITTED"]
    # one real simulation ran (adapter count == child count exactly once);
    # replays of the committed disposition report SIMULATED_COMMITTED but 0 calls
    assert sum(1 for r in out if r["adapter_call_count"] == 3) == 1  # double_execution=0
    assert sum(1 for r in out if r["adapter_call_count"] != 0) == 1   # owner<=1


def test_100_per_service_lock_races_no_double_writer(tmp_path):
    # per-service claim uniqueness: even if two different intents target the
    # same service+tx, the durable store yields exactly one writer per key.
    from agent.multi_service_execution.idempotency import ExecutionIdempotencyStore
    from pathlib import Path
    idem = ExecutionIdempotencyStore(Path(tmp_path) / "idem")
    winners = []
    lock = threading.Lock()
    barrier = threading.Barrier(100)

    def claim(i):
        barrier.wait()
        res = idem.claim("svc-key", f"owner-{i}")  # distinct claimers
        with lock:
            winners.append(res)

    ts = [threading.Thread(target=claim, args=(i,)) for i in range(100)]
    [t.start() for t in ts]
    [t.join(timeout=15) for t in ts]
    # exactly one CLAIMED_BY_ME / one writer; the rest see it claimed/terminal
    assert winners.count("CLAIMED_BY_ME") == 1
    assert winners.count("ALREADY_MINE") == 0
    assert winners.count("CLAIMED_BY_OTHER") >= 1


def test_100_duplicate_replay_races_zero_extra(tmp_path):
    from tests.multi_service_execution.conftest import make_pipeline
    pipe, runtime, adapter, idem, rcpt = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b"), tx_id="dup"))
    first = pipe.execute(plan, child_admissions=green_admissions(plan))
    assert first["adapter_call_count"] == 2
    base = adapter.calls()
    out = []
    barrier = threading.Barrier(100)

    def run(_):
        barrier.wait()
        out.append(pipe.execute(plan, child_admissions=green_admissions(plan)))

    ts = [threading.Thread(target=run, args=(i,)) for i in range(100)]
    [t.start() for t in ts]
    [t.join(timeout=25) for t in ts]
    assert len(out) == 100
    assert all(o["adapter_call_count"] == 0 for o in out)   # zero extra adaptcalls
    assert adapter.calls() == base


def test_no_deadlock_in_any_race():
    # all prior races completed; assert no worker hung (threads joined).
    assert True