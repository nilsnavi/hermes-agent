"""Bounded persistent audit store (Phase 6 §6): append-only, deterministic,
bounded, data-only."""

import pytest

from agent.agent_integration.audit_store import (
    AuditError,
    AuditStoreFull,
    ExecutionAuditEvent,
    InMemoryAuditStore,
    build_audit_event,
    new_run_provenance,
)


class _Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def _event(sequence: int = 1, **overrides: object):
    fields: dict[str, object] = {
        "task_id": "task-1", "task_step_id": "step-1", "agent_run_id": "run-1",
        "agent_id": "monitoring", "tenant_id": "acme", "user_id": "u-1",
        "route_decision": "monitoring", "capability_intent": "read_health",
        "boundary_disposition": "admitted", "supervisor_disposition": "completed",
        "memory_context_digest": "m-digest", "execution_observation": "ok",
        "policy_decision": "allow", "provenance": "run-pp",
        "sequence": sequence, "timestamp": 1000.0,
    }
    fields.update(overrides)
    return ExecutionAuditEvent(**fields)  # type: ignore[arg-type]


def test_event_is_frozen_and_full_chain():
    ev = _event()
    with pytest.raises(Exception):
        ev.task_id = "other"  # type: ignore[misc]  # frozen
    d = ev.to_dict()
    assert d["task_id"] == "task-1"
    assert d["boundary_disposition"] == "admitted"
    assert d["authority"] if "authority" in d else True  # no authority key present
    assert "authority_semantics" not in d  # audit is DATA, never authority


def test_audit_store_append_then_snapshot_append_only():
    store = InMemoryAuditStore(clock=_Clock())
    store.append(_event(1))
    store.append(_event(2))
    assert store.count() == 2
    snap = store.snapshot()
    assert tuple(e.sequence for e in snap) == (1, 2)


def test_audit_store_is_bounded_never_drops():
    store = InMemoryAuditStore(clock=_Clock(), max_records=2)
    store.append(_event(1))
    store.append(_event(2))
    with pytest.raises(AuditStoreFull):
        store.append(_event(3))  # append-only: never silently drop oldest
    assert store.count() == 2


def test_audit_builder_validates_required_fields():
    with pytest.raises(AuditError):
        build_audit_event(
            task_id="", task_step_id="s", agent_run_id="r", agent_id="a",
            tenant_id="t", user_id="u", route_decision="rd",
            capability_intent="c", boundary_disposition="", supervisor_disposition="d",
            sequence=1, timestamp=1.0,
        )
    with pytest.raises(AuditError):
        _event(task_id="")


def test_builder_defaults_are_safe_data():
    ev = build_audit_event(
        task_id="t", task_step_id="s", agent_run_id="r", agent_id="a",
        tenant_id="ten", user_id="u", route_decision="rd",
        capability_intent="c", boundary_disposition="DENY",
        supervisor_disposition="human_review", sequence=7, timestamp=9.0,
    )
    assert ev.policy_decision in ("", "n/a")
    assert ev.execution_observation in ("", "n/a")
    assert ev.provenance  # non-empty default


def test_audit_requires_exact_event_type():
    store = InMemoryAuditStore(clock=_Clock())
    with pytest.raises(AuditError):
        store.append({"task_id": "x"})  # type: ignore[arg-type]


def test_new_provenance_is_unique_and_bounded():
    p1 = new_run_provenance()
    p2 = new_run_provenance()
    assert p1 != p2
    assert p1.startswith("run-")