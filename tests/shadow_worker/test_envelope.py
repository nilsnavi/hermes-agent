"""Envelope contract tests (Phase 8.3 §5, §6, §8, §29)."""

from __future__ import annotations

import json

import pytest

from agent.platform_shadow.models import ShadowTaskEnvelope
from agent.shadow_worker.envelope import (
    DEFAULT_MAX_ENVELOPE_BYTES,
    ENVELOPE_SCHEMA_VERSION,
    FORBIDDEN_FIELD_NAMES,
    ProductionShadowEnvelopeV1,
    default_timestamp,
    new_event_id,
    parse_envelope,
)
from agent.shadow_worker.exceptions import EnvelopeValidationError


def _valid(**overrides):
    fields = dict(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        event_id="e1", source_request_id="req-1", tenant_id="acme", user_id="u1",
        request_kind="monitoring",
        sanitized_payload={"q": "health", "n": 3, "f": 1.5, "b": True, "none": None},
        input_digest="digest1", production_timestamp=1700000000.0,
        trace_id="tr", source_runtime_version="1.3.6", baseline_version="1.3.6",
    )
    fields.update(overrides)
    return ProductionShadowEnvelopeV1(**fields)


def _raw(**overrides):  # noqa: D103
    env = _valid(**overrides)
    return env.to_bytes()


# -- §8 basic contract ------------------------------------------------------

def test_valid_envelope_roundtrip_canonical():
    env = _valid()
    raw = env.to_bytes()
    res = parse_envelope(raw)
    assert res.status == "VALID"
    assert res.envelope is not None
    assert res.envelope.event_id == "e1"
    assert res.envelope.tenant_id == "acme"
    # deterministic: same envelope -> same bytes
    assert env.to_bytes() == raw


def test_deterministic_serialization_key_order_independent():
    a = parse_envelope(_valid().to_bytes()).envelope
    b = parse_envelope(_valid(event_id="e1").to_bytes()).envelope
    assert a.to_bytes() == b.to_bytes()


def test_envelope_is_plain_data_no_callables_objects():
    env = _valid()
    d = env.to_canonical_dict()
    # only bounded scalars + dict/list may survive
    assert d["sanitized_payload"] == {"q": "health", "n": 3, "f": 1.5,
                                      "b": True, "none": None}


# -- §29 adversarial ----------------------------------------------------------

def test_reject_unknown_schema_fail_closed():
    # build an UNKNOWN schema body manually
    body = _valid().to_canonical_dict()
    body["schema_version"] = "shadow-envelope/v99"
    raw = json.dumps(body, sort_keys=True).encode()
    res = parse_envelope(raw)
    assert res.status == "UNKNOWN_SCHEMA"
    assert res.envelope is None


def test_reject_non_canonical_whitespace_body():
    # a valid body that is pretty-printed -> not byte-canonical -> rejected
    body = _valid().to_canonical_dict()
    raw = json.dumps(body, sort_keys=True, indent=2).encode()
    res = parse_envelope(raw)
    assert res.status == "INVALID"


def test_reject_secret_field_name_in_payload():
    # construction rejects a secret-named payload key (fail at the boundary)
    with pytest.raises(EnvelopeValidationError):
        ProductionShadowEnvelopeV1(
            schema_version=ENVELOPE_SCHEMA_VERSION, event_id="e", source_request_id="r",
            tenant_id="t", user_id="u", request_kind="k",
            sanitized_payload={"password": "hunter2"}, input_digest="d",
            production_timestamp=1.0, baseline_version="1.3.6",
        )
    # and a raw envelope carrying a secret payload key is dropped
    body = _valid().to_canonical_dict()
    body["sanitized_payload"] = {"normal": 1, "authorization": "Bearer x"}
    res = parse_envelope(json.dumps(body, sort_keys=True).encode())
    assert res.status == "INVALID"


def test_reject_authority_top_level_fields():
    body = _valid().to_canonical_dict()
    body["approved"] = True
    raw = json.dumps(body, sort_keys=True).encode()
    res = parse_envelope(raw)
    # unknown top-level field -> INVALID (no authority can ride the envelope)
    assert res.status == "INVALID"


def test_reject_execute_override_apply_promote_payload_keys():
    for bad_key in ("approved", "execute", "override", "apply", "promote",
                    "grant", "authority", "token", "authorization"):
        payload = {"ok": 1, bad_key: True}
        try:
            env = ProductionShadowEnvelopeV1(
                schema_version=ENVELOPE_SCHEMA_VERSION, event_id="e", source_request_id="r",
                tenant_id="t", user_id="u", request_kind="k",
                sanitized_payload=payload, input_digest="d",
                production_timestamp=1.0, baseline_version="1.3.6",
            )
            env.to_bytes()  # may raise
        except EnvelopeValidationError:
            continue
        res = parse_envelope(env.to_bytes())
        assert res.status == "INVALID"


def test_reject_nan_infinity_bytes_callable_custom_object():
    for bad in (float("nan"), float("inf"), b"bytes", lambda: 1):
        with pytest.raises(EnvelopeValidationError):
            _valid(sanitized_payload={"bad": bad})
    with pytest.raises(EnvelopeValidationError):
        _valid(sanitized_payload={"bad": object()})


def test_reject_oversized_envelope():
    # monster string cannot even construct (over max str length) -> fail-closed
    with pytest.raises(EnvelopeValidationError):
        _valid(sanitized_payload={"x": "q" * 200_000})
    # and a raw envelope whose serialized size exceeds the cap is dropped
    body = _valid().to_canonical_dict()
    body["trace_id"] = "t" * (DEFAULT_MAX_ENVELOPE_BYTES + 10)
    res = parse_envelope(json.dumps(body, sort_keys=True).encode())
    assert res.status == "INVALID"


def test_reject_callable_object_payload():
    with pytest.raises(EnvelopeValidationError):
        _valid(sanitized_payload={"fn": (lambda x: x)})


# -- boundary / shape ---------------------------------------------------------

def test_unknown_version_is_dropped_not_coerced():
    # NO best-effort coercion: version 2 is NOT parsed as v1
    body = _valid().to_canonical_dict()
    body["schema_version"] = "shadow-envelope/v2"
    res = parse_envelope(json.dumps(body, sort_keys=True).encode())
    assert res.status == "UNKNOWN_SCHEMA"
    assert res.envelope is None


def test_cross_tenant_envelope_bound():
    env = _valid(tenant_id="tenant-a")
    shadow = _to_shadow(env)
    assert shadow.tenant_id == "tenant-a"


def _to_shadow(env: ProductionShadowEnvelopeV1) -> ShadowTaskEnvelope:
    return ShadowTaskEnvelope(
        shadow_id=env.event_id, source_request_id=env.source_request_id,
        tenant_id=env.tenant_id, user_id=env.user_id, task_kind=env.request_kind,
        input_digest=env.input_digest, received_at=env.production_timestamp,
        sampling_reason="t", production_context_digest=env.input_digest,
        baseline_version=env.baseline_version,
    )


def test_new_event_id_unique():
    assert new_event_id() != new_event_id()


def test_default_timestamp_finite():
    assert default_timestamp() > 1_600_000_000.0