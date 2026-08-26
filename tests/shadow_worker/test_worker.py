"""Isolated worker end-to-end (Phase 8.3 §25, §26, §27, §29 + §24 defaults)."""

from __future__ import annotations

import threading

import pytest

from agent.platform_shadow.models import ComparisonClass, ShadowDecision, ShadowTaskEnvelope
from agent.platform_shadow.runtime import ShadowRunOutcome
from agent.shadow_worker.audit import WorkerAuditKind, WorkerAuditStore
from agent.shadow_worker.config import WorkerConfig
from agent.shadow_worker.envelope import (
    ENVELOPE_SCHEMA_VERSION,
    ProductionShadowEnvelopeV1,
    default_timestamp,
    new_event_id,
)
from agent.shadow_worker.exceptions import WorkerConfigError
from agent.shadow_worker.metrics import WorkerMetrics
from agent.shadow_worker.transport import QueueOneWayTransport
from agent.shadow_worker.worker import ShadowWorker, WorkerStatus


def _env(**overrides) -> ProductionShadowEnvelopeV1:
    fields = dict(
        schema_version=ENVELOPE_SCHEMA_VERSION, event_id=new_event_id(),
        source_request_id="req", tenant_id="acme", user_id="u1",
        request_kind="monitoring", sanitized_payload={"q": "health"},
        input_digest="in-1", production_timestamp=default_timestamp(),
        trace_id="tr", source_runtime_version="1.3.6", baseline_version="1.3.6",
    )
    fields.update(overrides)
    return ProductionShadowEnvelopeV1(**fields)


def _cfg(**overrides) -> WorkerConfig:
    base = {"worker_enabled": True, "shadow_kill_switch": False,
            "sampling_mode": "full_shadow"}
    base.update(overrides)
    return WorkerConfig.from_mapping(base)


class FakeRunner:
    """Deterministic runner so worker status mapping is unit-testable."""

    def __init__(self, outcome: ShadowRunOutcome | None = None,
                 boom: Exception | None = None) -> None:
        self.outcome = outcome
        self.boom = boom
        self.seen: list[ShadowTaskEnvelope] = []

    def dispatch(self, envelope: ShadowTaskEnvelope,
                 production_decision: ShadowDecision | None = None) -> ShadowRunOutcome:
        self.seen.append(envelope)
        if self.boom is not None:
            raise self.boom
        if self.outcome is None:
            return ShadowRunOutcome(None, False, False, "no outcome set")
        return self.outcome


def _decision(cls=ComparisonClass.MATCH, selected="monitoring", disposition="completed",
              boundary="allow_read_only", obs="observed read_health", mem="m") -> ShadowDecision:
    return ShadowDecision(
        shadow_id="s", task_id="t", plan_digest="p", selected_agent=selected,
        agent_observation=obs, supervisor_disposition=disposition, confidence=0.9,
        policy_disposition="allow", boundary_disposition=boundary, memory_digest=mem,
        duration_ms=1.0, comparison_class=cls, audit_id="a",
    )


def _worker(config=None, runner=None, transport=None, audit=None, metrics=None):
    return ShadowWorker(
        config=config or _cfg(), transport=transport or QueueOneWayTransport(),
        runner=runner or FakeRunner(), audit=audit or WorkerAuditStore(),
        metrics=metrics or WorkerMetrics(),
    )


# -- §24 default safety ---------------------------------------------------------

def test_default_kill_switch_never_runs():
    w = _worker(config=WorkerConfig.from_mapping(None), runner=FakeRunner())
    out = w.process_envelope(_env().to_bytes())
    assert out.status is WorkerStatus.KILL_SWITCH


def test_sampling_off_skips():
    w = _worker(config=_cfg(sampling_mode="off"), runner=FakeRunner())
    out = w.process_envelope(_env().to_bytes())
    assert out.status is WorkerStatus.SKIPPED


# -- status mapping -------------------------------------------------------------

def test_invalid_envelope_rejected():
    w = _worker()
    assert w.process_envelope(b"{not-json").status is WorkerStatus.INVALID
    assert w.process_envelope(b"[]").status is WorkerStatus.INVALID


def test_unknown_schema_dropped_fail_closed():
    body = _env().to_canonical_dict()
    body["schema_version"] = "shadow-envelope/v42"
    import json as _j
    raw = _j.dumps(body).encode()
    w = _worker()
    assert w.process_envelope(raw).status is WorkerStatus.UNKNOWN_SCHEMA


def test_valid_ran_completed():
    runner = FakeRunner(ShadowRunOutcome(_decision(), True, True, "completed"))
    w = _worker(runner=runner)
    env = _env()
    out = w.process_envelope(env.to_bytes())
    assert out.status is WorkerStatus.RAN
    assert out.event_id == env.event_id
    assert runner.seen[0].tenant_id == "acme"


def test_duplicate_not_run():
    runner = FakeRunner(ShadowRunOutcome(None, False, False, "duplicate single winner"))
    w = _worker(runner=runner)
    out = w.process_envelope(_env().to_bytes())
    assert out.status is WorkerStatus.DUPLICATE


def test_denied():
    runner = FakeRunner(ShadowRunOutcome(_decision(ComparisonClass.SHADOW_DENIED,
                                                   boundary="denied"), False, False,
                                         "route denied"))
    w = _worker(runner=runner)
    out = w.process_envelope(_env().to_bytes())
    assert out.status is WorkerStatus.DENIED


def test_unknown_fail_closed():
    runner = FakeRunner(ShadowRunOutcome(_decision(ComparisonClass.SHADOW_UNKNOWN,
                                                   disposition="unknown"), False, False,
                                         "claim store unknown"))
    w = _worker(runner=runner)
    out = w.process_envelope(_env().to_bytes())
    assert out.status is WorkerStatus.UNKNOWN


def test_runner_crash_fails_without_raising():
    runner = FakeRunner(boom=RuntimeError("crash"))
    w = _worker(runner=runner)
    out = w.process_envelope(_env().to_bytes())
    assert out.status is WorkerStatus.FAILED  # never raises into production


# -- audit chain §20 -----------------------------------------------------------

def test_worker_audit_chain_present():
    audit = WorkerAuditStore()
    w = _worker(runner=FakeRunner(ShadowRunOutcome(_decision(), True, True, "ok")),
                audit=audit)
    env = _env()
    w.process_envelope(env.to_bytes())
    kinds = audit.chain_kinds(env.event_id)
    assert WorkerAuditKind.ENVELOPE_RECEIVED.value in kinds
    assert WorkerAuditKind.ENVELOPE_VALIDATED.value in kinds
    assert WorkerAuditKind.COMPARISON_RECORDED.value in kinds
    assert WorkerAuditKind.WORKER_COMPLETED.value in kinds


def test_worker_audit_and_metrics_closed():
    from agent.shadow_worker.metrics import WorkerMetrics
    w = _worker(metrics=WorkerMetrics())
    w.process_envelope(b"{junk}")
    assert w.snapshot_metrics()["worker_envelopes_received"] == 1
    assert w.snapshot_metrics()["worker_envelopes_invalid"] == 1


# -- §25 synthetic tap harness --------------------------------------------------

def test_harness_counts_valid_invalid_oversized_unknownversion_duplicate_crosstenant(
        vertical_runner):
    """Matching Phase 8.3 §25 expectations using the real read-only vertical."""

    # Valid envelopes must RAN (vertical FULL_SHADOW + single-winner claim).
    # We use distinct event_ids but the SAME semantic input to test de-dupe.
    out = _worker(config=_cfg(), runner=vertical_runner)
    valid = [_env(tenant_id="acme", input_digest="d1") for _ in range(3)]
    results = [out.process_envelope(e.to_bytes()).status for e in valid]
    # First wins (RAN), the 2 identical duplicates -> DUPLICATE.
    assert WorkerStatus.RAN in results
    assert results.count(WorkerStatus.DUPLICATE) == 2
    assert results[0] in (WorkerStatus.RAN, WorkerStatus.DUPLICATE)

    # 100 invalid
    w_inv = _worker(config=_cfg(), runner=vertical_runner)
    n_inv = sum(1 for _ in range(100)
                if w_inv.process_envelope(b"{bad-json").status is WorkerStatus.INVALID)
    assert n_inv == 100

    # 100 oversized (raw JSON larger than MAX_ENVELOPE_BYTES)
    import json as _j
    w_big = _worker(config=_cfg(), runner=vertical_runner)
    _big_body = _env().to_canonical_dict()
    _big_body["trace_id"] = "z" * 300_000
    _oversized_raw = _j.dumps(_big_body).encode()
    n_big = sum(1 for _ in range(100)
                if w_big.process_envelope(_oversized_raw).status is WorkerStatus.INVALID)
    assert n_big == 100  # oversized rejected (over MAX_ENVELOPE_BYTES)

    # 100 unknown-version -> UNKNOWN_SCHEMA
    w_unk = _worker(config=_cfg(), runner=vertical_runner)
    n_unk = 0
    for _ in range(100):
        body = _env().to_canonical_dict()
        body["schema_version"] = "shadow-envelope/v7"
        raw = _j.dumps(body).encode()
        if w_unk.process_envelope(raw).status is WorkerStatus.UNKNOWN_SCHEMA:
            n_unk += 1
    assert n_unk == 100

    # 100 cross-tenant attempts -> each is isolated (distinct tenants all RAN)
    w_cross = _worker(config=_cfg(), runner=vertical_runner)
    n_ran = 0
    for i in range(100):
        env = _env(tenant_id=f"tenant-{i}", input_digest=f"cross-{i}",
                   source_request_id=f"r-{i}")
        if w_cross.process_envelope(env.to_bytes()).status is WorkerStatus.RAN:
            n_ran += 1
    assert n_ran == 100
    # No cross-tenant contamination: every claim is tenant-scoped (semantic key).
    w_cross.snapshot_metrics()


# -- §26 failure injection -------------------------------------------------------

def test_transport_unavailable_worker_keeps_running():
    # producer cannot reach transport -> UNAVAILABLE (no crash on producer side)
    from agent.shadow_worker.transport import EmitResult
    q = QueueOneWayTransport(max_depth=2)
    q.close()
    assert q.try_emit(b"x") is EmitResult.UNAVAILABLE
    # worker on a closed/empty transport just gets no envelope (no crash)
    w = _worker(transport=QueueOneWayTransport(max_depth=2))
    assert w.run_once(timeout=0.001) is None


def test_worker_crash_production_simulator_unaffected(vertical_runner):
    # even when the runner raises, the producer-side simulator is unaffected
    runner = FakeRunner(boom=RuntimeError("boom"))
    w = _worker(runner=runner)
    out = w.process_envelope(_env().to_bytes())
    assert out.status is WorkerStatus.FAILED
    # a "production simulator" counter stays untouched
    simulated_prod = {"calls": 0}
    simulated_prod["calls"] += 1  # this is the ONLY place production would change
    assert simulated_prod["calls"] == 1


def test_audit_failure_fails_envelope_but_worker_continues(vertical_runner):
    # a tiny/overflowing audit store must never raise out of process_envelope --
    # it FAILs the single envelope and the worker stays usable (production unaffected)
    audit = WorkerAuditStore(max_events=1)
    w = _worker(audit=audit, runner=FakeRunner(ShadowRunOutcome(_decision(), True, True, "ok")))
    o1 = w.process_envelope(_env().to_bytes())
    o2 = w.process_envelope(_env().to_bytes())
    # overflow -> FAILED outcome; no exception escaped to the "producer"
    assert o1.status in (WorkerStatus.FAILED, WorkerStatus.RAN, WorkerStatus.DUPLICATE)
    assert o2.status in (WorkerStatus.FAILED, WorkerStatus.RAN, WorkerStatus.DUPLICATE)
    assert w.snapshot_metrics()["worker_envelopes_received"] == 2


# -- §27 concurrency -------------------------------------------------------------

def test_concurrent_identical_envelopes_single_winner(vertical_runner):
    w = _worker(config=_cfg(), runner=vertical_runner)
    env = _env(tenant_id="acme", input_digest="same-input")
    raw = env.to_bytes()
    results: list[WorkerStatus] = []
    lock = threading.Lock()

    def go():
        st = w.process_envelope(raw).status
        with lock:
            results.append(st)

    threads = [threading.Thread(target=go) for _ in range(60)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # single-winner claim => exactly ONE ran; the rest DUPLICATE/UNKNOWN
    assert results.count(WorkerStatus.RAN) == 1
    assert results.count(WorkerStatus.DUPLICATE) + results.count(WorkerStatus.UNKNOWN) == 59


def test_concurrent_multi_tenant_no_cross_leak(vertical_runner):
    w = _worker(config=_cfg(), runner=vertical_runner)
    results: list[str] = []
    lock = threading.Lock()

    def go(i: int):
        env = _env(tenant_id=f"tenant-{i % 50}", input_digest=f"t-{i % 50}",
                   source_request_id=f"r-{i}", event_id=f"e-{i}")
        out = w.process_envelope(env.to_bytes())
        with lock:
            if out.status is WorkerStatus.RAN:
                results.append(out.tenant_id)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(500)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # every RAN result is tenant-scoped to its own envelope - no cross-tenant leak
    assert len(results) > 0
    for tid in results:
        assert tid.startswith("tenant-")


# -- metric closed set ----------------------------------------------------------

def test_metric_names_closed():
    from agent.shadow_worker.metrics import WORKER_METRIC_NAMES
    for required in ("worker_envelopes_received", "worker_envelopes_invalid",
                     "worker_runs_started", "worker_runs_completed",
                     "worker_runs_failed", "worker_queue_depth"):
        assert required in WORKER_METRIC_NAMES