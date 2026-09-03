from dataclasses import fields

from agent.capability_broker.audit import (
    CapabilityAuditEvent,
    InMemoryAuditSink,
    NullAuditSink,
)
from agent.capability_broker.context import TrustedSurface


def event():
    return CapabilityAuditEvent(
        request_id="req-1",
        operation="testit.projects.read",
        tenant_id="tenant-1",
        principal_id="principal-1",
        surface=TrustedSurface.DESKTOP,
        decision="allow",
        result="success",
        reason_code="OK",
        duration_ms=5,
    )


def test_audit_event_schema_contains_no_sensitive_payload_fields():
    names = {field.name for field in fields(CapabilityAuditEvent)}

    forbidden = {
        "arguments",
        "token",
        "secret",
        "headers",
        "response",
        "exception",
        "password",
        "authorization",
    }

    assert names.isdisjoint(forbidden)


def test_in_memory_sink_records_immutable_events():
    sink = InMemoryAuditSink()
    item = event()

    sink.record(item)

    assert sink.events == (item,)


def test_null_sink_accepts_valid_event():
    NullAuditSink().record(event())
