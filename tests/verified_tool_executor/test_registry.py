"""Sprint 1.3.2 §6-§9 — registry binding, schemas, disable route."""

import pytest

from agent.capability_router.registry import RegistryValidationError
from agent.verified_tool_executor.adapter import AdapterResult
from agent.verified_tool_executor.registry import (
    EMPTY_ARGUMENT_SCHEMA,
    ANY_DICT_OUTPUT_SCHEMA,
    VerifiedToolRegistry,
    validate_against_schema,
    validate_schema_value,
)
from tests.verified_tool_executor.conftest import RecordingAdapter


def test_bind_verified_tool(registry, fake_adapter):
    registry.bind("runtime_status", fake_adapter)
    assert registry.has("runtime_status")
    assert registry.names() == ["runtime_status"]
    binding = registry.resolve("runtime_status")
    assert binding is not None
    assert binding.descriptor.verified is True
    assert binding.descriptor.capability.value == "STATUS_RUNTIME"
    assert binding.descriptor.side_effect == "READ_ONLY"


def test_bind_unknown_tool_rejected(registry, fake_adapter):
    with pytest.raises(RegistryValidationError):
        registry.bind("not_a_real_tool", fake_adapter)


def test_bind_all_migrated_tools(registry):
    """§27 — the full migrated surface binds cleanly."""
    for tool in ("runtime_status", "gateway_status",
                 "integration_status", "scheduler_status",
                 "provider_status", "operational_log_search"):
        registry.bind(tool, RecordingAdapter())
    assert registry.names() == [
        "gateway_status", "integration_status",
        "operational_log_search", "provider_status",
        "runtime_status", "scheduler_status",
    ]


def test_bind_rejects_write_descriptor():
    """A non-READ_ONLY descriptor is outside the 1.3.2 surface.

    The CapabilityRegistry itself cannot contain a WRITE descriptor
    that contradicts the verified contract (§27) — construction with
    validate=False still refuses at bind time in the executor layer.
    """
    from agent.capability_router.models import CapabilityDescriptor
    from agent.capability_router.capabilities import Capability

    from agent.capability_router.registry import CapabilityRegistry

    custom = CapabilityRegistry(
        [
            CapabilityDescriptor(
                capability=Capability.STATUS_RUNTIME,
                tool_name="runtime_status",
                side_effect="WRITE",
                network=True,
            )
        ],
        validate=False,  # simulate a drifted descriptor
    )
    reg = VerifiedToolRegistry(capability_registry=custom)
    with pytest.raises(RegistryValidationError):
        reg.bind("runtime_status", RecordingAdapter())


def test_resolve_returns_none_for_unbound():
    reg = VerifiedToolRegistry()
    assert reg.resolve("runtime_status") is None
    assert reg.has("runtime_status") is False


def test_disable_tool_fail_closed(registry, fake_adapter):
    """§34 — a disabled route can never execute again."""
    registry.bind("runtime_status", fake_adapter)
    registry.disable_tool("runtime_status")
    assert registry.resolve("runtime_status") is None
    assert registry.has("runtime_status") is False


def test_argument_schema_validation():
    schema = {
        "fields": {
            "query": {"type": "str", "required": True, "max_len": 500},
            "limit": {"type": "int", "min": 1, "max": 50},
            "source": {"type": "str", "allowed": ["GATEWAY_LOG", "EVENTS"]},
        }
    }
    assert validate_against_schema(schema, {}) != []
    assert validate_against_schema(
        schema, {"query": "err", "limit": 5, "source": "EVENTS"}) == []
    errors = validate_against_schema(
        schema, {"query": "x", "limit": 999})
    assert any("limit" in e for e in errors)
    errors = validate_against_schema(
        schema, {"query": "x", "source": "BOGUS"})
    assert any("source" in e for e in errors)
    # unknown keys fail closed
    errors = validate_against_schema(
        schema, {"query": "x", "limit": 5, "hack": True})
    assert any("unknown key" in e for e in errors)


def test_schema_value_type_checks():
    assert validate_schema_value("n", 5, {"type": "int"}) is None
    assert validate_schema_value("n", "x", {"type": "int"}) is not None
    assert validate_schema_value("n", True, {"type": "int"}) is not None
    assert validate_schema_value("n", 3, {"type": "int", "min": 4}) is not None


def test_empty_argument_schema_rejects_any_key():
    errors = validate_against_schema(
        EMPTY_ARGUMENT_SCHEMA, {"anything": 1})
    assert any("unknown key" in e for e in errors)
    assert validate_against_schema(EMPTY_ARGUMENT_SCHEMA, {}) == []


def test_output_schema_any_dict():
    binding = VerifiedToolRegistry().bind(
        "runtime_status", RecordingAdapter()).resolve("runtime_status")
    assert binding.validate_output({"a": 1, "nested": {"x": []}}) == []


def test_binding_output_validation_rejects_non_dict():
    """§9 — malformed output (non-dict) → INVALID_TOOL_RESULT."""
    binding = VerifiedToolRegistry().bind(
        "runtime_status", RecordingAdapter()).resolve("runtime_status")
    errors = binding.validate_output(["not", "a", "dict"])
    assert errors and "dict" in errors[0]
    assert binding.validate_output({"ok": True}) == []
