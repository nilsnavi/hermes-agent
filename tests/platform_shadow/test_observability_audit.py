"""Shadow observability + audit safety (Phase 7 §11, §12, §13, §27)."""

import pytest

from agent.platform_shadow.audit import (
    SHADOW_AUDIT_CHAIN_ORDER,
    ShadowAuditKind,
    ShadowAuditStore,
)
from agent.platform_shadow.observability import (
    SHADOW_METRIC_NAMES,
    ShadowMetrics,
    ShadowTracer,
)


def test_metrics_closed_names_only():
    m = ShadowMetrics()
    assert set(m.snapshot()) == SHADOW_METRIC_NAMES
    assert "shadow_tasks_received" in SHADOW_METRIC_NAMES
    m.increment("shadow_tasks_received")
    assert m.get("shadow_tasks_received") == 1
    with pytest.raises(ValueError):
        m.increment("user_prompt_injected")  # dynamic name rejected


def test_metrics_reject_secrets_in_labels():
    m = ShadowMetrics()
    with pytest.raises(ValueError):
        m.increment("shadow_agent_selected", labels={"agent_id": "user@example.com"})
    with pytest.raises(ValueError):
        m.increment("shadow_agent_selected", labels={"agent_id": "tok_abcdefghijklmnop"})
    with pytest.raises(ValueError):
        m.increment("shadow_agent_selected", labels={"agent_id": "echo prompt full text"})
    # A safe fixed enum value is fine.
    m.increment("shadow_agent_selected", labels={"agent_id": "monitoring"})
    assert m.get("shadow_agent_selected") == 1
    # Unknown label NAME is rejected.
    with pytest.raises(ValueError):
        m.increment("shadow_agent_selected", labels={"tenant": "acme"})


def test_metrics_cardinality_bounded():
    m = ShadowMetrics()
    # Only a fixed label set is allowed, so cardinality is bounded by design.
    allowed = {"shadow_agent_selected", "shadow_tasks_sampled"}
    assert SHADOW_METRIC_NAMES == {
        "shadow_tasks_received", "shadow_tasks_sampled", "shadow_tasks_completed",
        "shadow_tasks_failed", "shadow_tasks_unknown", "shadow_human_review",
        "shadow_route_denied", "shadow_policy_denied", "shadow_boundary_denied",
        "shadow_memory_denied", "shadow_registry_drift", "shadow_duplicate_runs",
        "shadow_duration_ms", "shadow_agent_selected", "shadow_comparison_match",
        "shadow_comparison_mismatch",
    }
    del allowed


def test_duration_gauge():
    m = ShadowMetrics()
    m.gauge("shadow_duration_ms", 12.5)
    assert m.duration_ms() == 12.5


def test_tracer_correlation_only_not_authority():
    t = ShadowTracer()
    t.record("route_selected", "agent:monitoring", "req:1")
    t.record("boundary_decided", "boundary:allow", "req:1")
    assert t.chain() == ("agent:monitoring", "boundary:allow")
    assert t.kinds()[0] == "route_selected"
    # Trace ids are correlation only; no authority/execution method exists.
    assert not hasattr(t, "execute")
    assert not hasattr(t, "grant")


def test_audit_append_only_ordered_chain():
    store = ShadowAuditStore()
    for kind in ShadowAuditKind:
        store.append(shadow_id="s", kind=kind, node_id="n", parent_id="s")
    kinds = store.chain_kinds("s")
    assert kinds == SHADOW_AUDIT_CHAIN_ORDER
    assert store.count() == len(ShadowAuditKind)


def test_audit_bounded_never_drops():
    store = ShadowAuditStore(max_events=3)
    for i in range(3):
        store.append(shadow_id="s", kind=ShadowAuditKind.SHADOW_RECEIVED, node_id=str(i))
    with pytest.raises(OverflowError):
        store.append(shadow_id="s", kind=ShadowAuditKind.SHADOW_SAMPLED, node_id="x")


def test_audit_does_not_carry_instruction():
    ev = ShadowAuditStore().append(
        shadow_id="s", kind=ShadowAuditKind.BOUNDARY_DECIDED, node_id="n", parent_id="s",
        detail="decision",
    )
    assert not hasattr(ev, "execute")
    assert not hasattr(ev, "grant")
    assert not hasattr(ev, "instruction")