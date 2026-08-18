"""Sprint 1.3.2 §53 — performance: execution wrapper overhead.

Measured WITHOUT underlying tool latency (a no-op adapter). Target:
p95 < 1 ms preferred; existing total response budgets stay within
gates.
"""

import statistics
import time

from agent.verified_tool_executor.adapter import AdapterResult
from agent.verified_tool_executor.executor import VerifiedToolExecutor
from agent.verified_tool_executor.models import ExecutionStatus
from agent.verified_tool_executor.registry import VerifiedToolRegistry
from agent.verified_tool_executor.receipts import MemoryReceiptStore
from tests.verified_tool_executor.conftest import (
    RecordingAdapter,
    make_request,
)


class NoopAdapter:
    def execute(self, context, arguments):
        return AdapterResult(output={"ok": True})


def test_wrapper_overhead_p95_below_1ms():
    """§53 — the contract wrapper (validation + receipt + events) adds
    < 1 ms p95 on top of the tool itself."""
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", NoopAdapter())
    ex = VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())

    # warmup + measure N executions (unique idempotency keys)
    N = 300
    durations = []
    for i in range(N):
        req = make_request(request_id=f"p{i}", run_id="perf",
                           step_id=f"s{i}", idempotency_key=f"k{i}")
        t0 = time.perf_counter()
        res = ex.execute(req)
        durations.append((time.perf_counter() - t0) * 1000.0)
        assert res.status is ExecutionStatus.SUCCEEDED

    durations.sort()
    p95 = durations[int(len(durations) * 0.95)]
    p50 = statistics.median(durations)
    print(f"\nPERF: N={N} p50={p50:.4f}ms p95={p95:.4f}ms "
          f"max={durations[-1]:.4f}ms")
    assert p95 < 1.0, f"p95={p95:.4f}ms exceeds 1ms gate"


def test_overhead_stable_under_duplicates():
    """Duplicate (replayed) requests are cheaper — no adapter call."""
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", NoopAdapter())
    ex = VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())
    req = make_request()
    ex.execute(req)
    t0 = time.perf_counter()
    for _ in range(200):
        ex.execute(req)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 1000.0  # 200 replays < 1 s total


def test_rejected_requests_cheap():
    reg = VerifiedToolRegistry()
    reg.bind("runtime_status", NoopAdapter())
    ex = VerifiedToolExecutor(reg, receipts=MemoryReceiptStore())
    req = make_request(policy_verdict="LEGACY")
    t0 = time.perf_counter()
    for _ in range(500):
        ex.execute(req)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 1000.0
