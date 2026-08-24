"""Sprint 1.3.17 — canonical lock coordination revalidation (§15)."""

from __future__ import annotations

from agent.multi_service_execution import lock_owner_valid, lockset_digest
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def _lock(**kw):
    base = {"owner_runtime": "rt-1", "tx": "tx-1", "generation": 1,
            "nonce": "n", "pid": 1234, "process_start_identity": "start-1",
            "expiry_monotonic": 5000.0}
    base.update(kw)
    return base


def test_live_lock_valid():
    ok, reason = lock_owner_valid(_lock(), expected_tx="tx-1", expected_generation=1,
                                  owner_runtime="rt-1", expected_service_set={"svc-a"},
                                  now_monotonic=100.0)
    assert ok and reason == "live-owner"


def test_foreign_owner_denied():
    ok, _ = lock_owner_valid(_lock(owner_runtime="rt-attacker"),
                             expected_tx="tx-1", expected_generation=1,
                             owner_runtime="rt-1", expected_service_set={"svc-a"},
                             now_monotonic=100.0)
    assert ok is False


def test_tx_mismatch_denied():
    ok, reason = lock_owner_valid(_lock(), expected_tx="other-tx", expected_generation=1,
                                  owner_runtime="rt-1", expected_service_set={"svc-a"},
                                  now_monotonic=100.0)
    assert ok is False and "tx" in reason


def test_stale_lock_denied():
    ok, reason = lock_owner_valid(_lock(expiry_monotonic=50.0),
                                  expected_tx="tx-1", expected_generation=1,
                                  owner_runtime="rt-1", expected_service_set={"svc-a"},
                                  now_monotonic=100.0)
    assert ok is False and "stale" in reason


def test_pid_reuse_denied():
    ok, reason = lock_owner_valid(_lock(pid_reuse=True), expected_tx="tx-1",
                                  expected_generation=1, owner_runtime="rt-1",
                                  expected_service_set={"svc-a"}, now_monotonic=100.0)
    assert ok is False and "pid" in reason


def test_one_lost_lock_blocks_pipeline_before_adapter(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan),
                         locks_live_owned=False)
    assert r["adapter_call_count"] == 0
    assert r["global_state"] == "EXECUTION_DENIED"


def test_lockset_digest_stable():
    r1 = {"svc-a": {"nonce": "n1"}, "svc-b": {"nonce": "n2"}}
    r2 = {"svc-b": {"nonce": "n2"}, "svc-a": {"nonce": "n1"}}
    assert lockset_digest(r1) == lockset_digest(r2)  # canonical ordering