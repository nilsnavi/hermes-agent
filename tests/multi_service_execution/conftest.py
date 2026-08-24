"""Sprint 1.3.17 shared fixtures."""

from __future__ import annotations

from agent.multi_service_coordination.models import (
    BlastRadius, MultiServiceChangePlan, ServiceSubPlan,
)
from agent.multi_service_execution import ExecutionMode
from agent.multi_service_execution.models import MultiServiceExecutionPlan
from agent.multi_service_execution.authority import ExecutionRuntime
from agent.multi_service_execution.fake_adapter import FakeServiceAdapter
from agent.multi_service_execution.idempotency import ExecutionIdempotencyStore
from agent.multi_service_execution.pipeline import ExecutionPipeline, build_execution_plan
from agent.multi_service_execution.receipt import ExecutionReceiptStore

ENV_REHEARSAL = {
    "HERMES_MULTI_SERVICE_EXECUTION_V2_ENABLED": "true",
    "HERMES_MULTI_SERVICE_EXECUTION_V2_MODE": "rehearsal",
}
ENV_SHADOW = {
    "HERMES_MULTI_SERVICE_EXECUTION_V2_ENABLED": "true",
    "HERMES_MULTI_SERVICE_EXECUTION_V2_MODE": "shadow",
}


def make_subplan(service_id: str, *, op: str = "reload", risk: str = "LOW",
                 blast: str = "SERVICE", approval: str = "",
                 budget: str = "") -> ServiceSubPlan:
    approval = approval or f"ap-{service_id}"
    budget = budget or f"bud-{service_id}"
    return ServiceSubPlan(
        service_id=service_id, service_profile_version=1, operation=op,
        identity_fingerprint=f"id-{service_id}", config_fingerprint=f"cfg-{service_id}",
        dependency_digest=f"dep-{service_id}", pre_health="ok",
        required_post_health=f"post-{service_id}", rollback_strategy="reverse",
        risk=risk, blast_radius=blast, consumer_set=(),
        approval_reference=approval, budget_reference=budget,
        idempotency_key=f"idem-{service_id}",
    )


def make_coord_plan(services: tuple[str, ...], *, tx_id: str = "tx-1",
                    exec_order: tuple[str, ...] | None = None) -> MultiServiceChangePlan:
    subs = tuple(make_subplan(s) for s in services)
    order = exec_order if exec_order is not None else services
    p = MultiServiceChangePlan(
        plan_id=f"plan-{tx_id}", transaction_id=tx_id, baseline_sha="base-sha",
        coordinator_version="1.3.15", created_at=0.0, expires_at=10_000_000.0,
        service_set=subs, dependency_graph_digest="graph-digest",
        execution_order=order, rollback_order=tuple(reversed(order)),
        operation_set=tuple(f"op-{s}" for s in services),
        risk_before="LOW", risk_after="LOW", blast_radius="SERVICE",
        registry_digest="registry-digest", plan_hash="ph",
    )
    return p


def make_exec_plan(coord_plan, *, mode: ExecutionMode = ExecutionMode.REHEARSAL,
                   generation: int = 1, **kw) -> "MultiServiceExecutionPlan":
    return build_execution_plan(coord_plan, execution_mode=mode, generation=generation, **kw)


def make_custom_plan(service_id: str, *, operation: str = "reload",
                     blast: str = "SERVICE") -> "MultiServiceExecutionPlan":
    from agent.multi_service_coordination.models import MultiServiceChangePlan
    sub = make_subplan(service_id, op=operation, blast=blast)
    cp = MultiServiceChangePlan(
        plan_id=f"plan-{service_id}", transaction_id=f"tx-{service_id}",
        baseline_sha="base-sha", coordinator_version="1.3.15",
        created_at=0.0, expires_at=10_000_000.0, service_set=(sub,),
        dependency_graph_digest="g", execution_order=(service_id,),
        rollback_order=(service_id,), operation_set=(operation,),
        risk_before="LOW", risk_after="LOW", blast_radius="SERVICE",
        registry_digest="r", plan_hash="ph",
    )
    return make_exec_plan(cp)


def make_pipeline(tmp_path, *, env=None, mode: ExecutionMode = ExecutionMode.REHEARSAL):
    root = tmp_path / "msexec"
    runtime = ExecutionRuntime()
    adapter = FakeServiceAdapter()
    idem = ExecutionIdempotencyStore(root / "idem")
    receipts = ExecutionReceiptStore(root / "receipts")
    pipeline = ExecutionPipeline(runtime, adapter, idem, receipts,
                                 clock=lambda: 1000.0,
                                 env=dict(ENV_REHEARSAL if env is None else env))
    return pipeline, runtime, adapter, idem, receipts


def green_admissions(plan) -> dict[str, bool]:
    """Fail-closed child admission set (every child independently PASS)."""
    return {s: True for s in plan.service_set}