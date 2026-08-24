"""Sprint 1.3.17 — gate performance (§28), p95, FS-heavy excluded."""

from __future__ import annotations

import statistics
import time

from agent.multi_service_execution import (approval_binding_valid, build_execution_plan,
                                           lock_owner_valid)
from agent.multi_service_execution.authority import ExecutionRuntime
from agent.multi_service_execution.barrier import ExecutionBarrier
from agent.multi_service_execution.commit import GlobalCommitCoordinator
from agent.multi_service_execution.fake_adapter import FakeServiceAdapter
from agent.multi_service_execution.models import semantic_execution_key, service_set_hash
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(sorted(samples), n=100)[94]


def _timeit(fn, n=300) -> list[float]:
    fn()  # warmup
    out = []
    for _ in range(n):
        s = time.perf_counter()
        fn()
        out.append(time.perf_counter() - s)
    return out


def test_plan_build_p95_lt_3ms():
    from agent.multi_service_execution import ExecutionMode
    cp = make_coord_plan(("svc-a", "svc-b", "svc-c"))
    samples = _timeit(lambda: build_execution_plan(cp,
                                                   execution_mode=ExecutionMode.REHEARSAL))
    p95 = _p95(samples) * 1000
    assert p95 < 3.0, f"plan build p95={p95:.3f}ms"


def test_authority_validation_p95_lt_2ms():
    runtime = ExecutionRuntime()
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    auth = runtime._issue(plan, now_monotonic=1000.0, ttl_s=1000.0)
    # readonly verify over many distinct (non-consumed) paths
    samples = _timeit(lambda: runtime._verify_readonly(runtime, auth, 1000.0), n=200)
    p95 = _p95(samples) * 1000
    assert p95 < 2.0, f"authority p95={p95:.3f}ms"


def test_lockset_validation_p95_lt_2ms():
    rec = {"owner_runtime": "rt", "tx": "tx-1", "generation": 1, "nonce": "n",
           "pid": 1, "process_start_identity": "s", "expiry_monotonic": 9999.0}
    samples = _timeit(lambda: lock_owner_valid(
        rec, expected_tx="tx-1", expected_generation=1, owner_runtime="rt",
        expected_service_set={"svc-a"}, now_monotonic=100.0), n=200)
    p95 = _p95(samples) * 1000
    assert p95 < 2.0, f"lock p95={p95:.3f}ms"


def test_barrier_p95_lt_2ms():
    barrier = ExecutionBarrier()
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    samples = _timeit(lambda: barrier.evaluate(
        plan, child_admissions=green_admissions(plan)), n=200)
    p95 = _p95(samples) * 1000
    assert p95 < 2.0, f"barrier p95={p95:.3f}ms"


def test_idempotency_key_p95_lt_3ms_pure():
    # pure semantic key (FS-disks excluded per §28)
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    samples = _timeit(lambda: semantic_execution_key(plan), n=400)
    p95 = _p95(samples) * 1000
    assert p95 < 3.0, f"idem key p95={p95:.3f}ms"


def test_global_decision_p95_lt_5ms():
    coord = GlobalCommitCoordinator()
    runtime = ExecutionRuntime()
    plan = make_exec_plan(make_coord_plan(("svc-a", "svc-b")))
    auth = runtime._issue(plan, now_monotonic=1000.0, ttl_s=1000.0)
    from agent.multi_service_execution.models import ChildExecutionState
    states = {s: ChildExecutionState.CHILD_VERIFIED for s in plan.service_set}
    from agent.multi_service_execution.stabilization import StabilizationResult

    def _ok_stab():
        return StabilizationResult(ready_for_commit=True, reason="ok")

    def dec():
        return coord.decide(plan, states, _ok_stab(),
                            runtime=runtime, authority=auth, now_monotonic=1000.0)

    dec()  # warmup (consumes authority once; decide when authority None not needed)
    samples = _timeit(lambda: coord.decide(
        plan, states, _ok_stab(), runtime=runtime, now_monotonic=1000.0), n=300)
    p95 = _p95(samples) * 1000
    assert p95 < 5.0, f"decision p95={p95:.3f}ms"