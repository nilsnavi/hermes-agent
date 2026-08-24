"""Sprint 1.3.17 — durable exactly-once idempotency (§13)."""

from __future__ import annotations

import threading

from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def test_first_execution_commits_once(tmp_path):
    pipeline, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    r = pipeline.execute(plan, child_admissions=green_admissions(plan))
    assert r["global_state"] == "SIMULATED_COMMITTED"
    assert r["adapter_call_count"] == 2


def test_duplicate_intent_replays_terminal_zero_adapter(tmp_path):
    pipeline, runtime, adapter, idem, _ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    first = pipeline.execute(plan, child_admissions=green_admissions(plan))
    assert first["adapter_call_count"] == 2
    calls_before = adapter.calls()
    # a duplicate dispatch (same semantic key) replays the prior terminal
    # result WITHOUT a second adapter call.
    dup = pipeline.execute(plan, child_admissions=green_admissions(plan))
    assert dup["replayed"] is True
    assert dup["adapter_call_count"] == 0
    assert adapter.calls() == calls_before


def test_concurrent_claimers_exactly_one_winner(tmp_path):
    pipeline, runtime, adapter, idem, _ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    outcomes = []
    barrier = threading.Barrier(20)

    def runner(_i):
        barrier.wait()
        outcomes.append(pipeline.execute(plan, child_admissions=green_admissions(plan)))

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join(timeout=15) for t in threads]
    committed = [o for o in outcomes if o["global_state"] == "SIMULATED_COMMITTED"]
    # the DURABLE claim lets the winner + later replays both report as a
    # committed disposition, but exactly ONE dispatched the real simulation.
    # global_adapter_owner <= 1 == adapter_call_count full-run count.
    assert sum(1 for o in outcomes if o["adapter_call_count"] == 1) == 1
    assert sum(1 for o in outcomes if o["adapter_call_count"] != 0) == 1


def test_unknown_outcome_stored_not_auto_retried(tmp_path):
    from agent.multi_service_execution import semantic_execution_key
    pipeline, runtime, adapter, idem, _ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    scenario = {"svc-a": {"outcome": "ADAPTER_UNKNOWN_OUTCOME"}}
    first = pipeline.execute(plan, scenario=scenario,
                             child_admissions=green_admissions(plan))
    assert first["global_state"] == "EXECUTION_UNKNOWN"
    st = idem.get(semantic_execution_key(plan))
    # A second dispatch on the SAME semantic key must NOT invoke the adapter
    # again: the prior UNKNOWN is terminal -> replay with 0 adapter calls.
    dup = pipeline.execute(plan, scenario=scenario,
                           child_admissions=green_admissions(plan))
    assert dup["replayed"] is True
    assert dup["adapter_call_count"] == 0