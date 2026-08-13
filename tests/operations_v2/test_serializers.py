"""Serializer tests (Sprint 1.0.6.3 §10, §21)."""

import json

from agent.operations_v2.models import OperatorIdentity, RunSummary, RunTimelineItem
from agent.operations_v2.serializers import (
    dto_list_to_json,
    sanitize_note,
    summarize_event_payload,
    to_json,
)


def test_event_whitelist_mapping():
    """§10 — whitelist projection drops everything not listed."""
    payload = {
        "step": "step-1", "tool": "search", "input_hash": "abc",
        "secret_arg": "supersecret", "raw_output": {"x": 1},
    }
    out = summarize_event_payload("TOOL_STARTED", payload)
    assert out == {"step_id": "step-1", "tool_name": "search",
                   "input_hash": "abc"}
    assert "secret_arg" not in out
    assert "raw_output" not in out
    # unknown event types → empty projection
    assert summarize_event_payload("WEIRD_EVENT", payload) == {}


def test_stable_json_sorted_keys():
    value = {"b": 1, "a": {"z": 2, "y": 3}, "status": "running"}
    blob = to_json(value)
    assert json.loads(blob) == value
    # sorted keys
    assert blob.index('"a"') < blob.index('"b"')


def test_json_roundtrip_dtos():
    summary = RunSummary(
        run_id="r1", status="completed", task_type="internal",
        created_at="2026-08-10T00:00:00+00:00", started_at=None,
        completed_at=None, duration_ms=None, plan_status=None,
        step_count=1, tool_calls=2,
    )
    data = json.loads(to_json(summary.to_dict()))
    assert data["run_id"] == "r1"
    assert data["tool_calls"] == 2


def test_enum_values_in_json():
    from agent.operations_v2.models import HealthStatus

    assert json.loads(to_json({"s": HealthStatus.DEGRADED}))["s"] == "degraded"


def test_sanitize_note():
    assert sanitize_note("   short note  ") == "short note"
    assert sanitize_note("x" * 500) == "x" * 200 + "…"
    assert sanitize_note(None) is None
    assert sanitize_note("") is None


def test_dto_list_json():
    items = [RunTimelineItem(event_id=1, timestamp=None, event_type="A",
                             step_id=None, tool_name=None, status=None,
                             reason_code=None)]
    blob = dto_list_to_json(items)
    assert json.loads(blob)[0]["event_type"] == "A"


def test_operator_identity_dict():
    op = OperatorIdentity(operator_id="op", source="cli",
                          roles=frozenset({"a", "b"}), authenticated=True)
    d = op.to_dict()
    assert d["roles"] == ["a", "b"]
    assert d["authenticated"] is True
