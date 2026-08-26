"""ProductionShadowEnvelopeV1 — canonical, versioned, boundable shadow envelope.

Phase 8.3 §5, §6, §8, §29.

A shadow envelope is the ONLY thing a production gateway ever hands to the
isolated shadow worker.  It is IMMUTABLE DATA with a strict, canonical field
set and a deterministic serialization contract.  These hard properties are
what make the audit chain meaningful and make the worker decoupled from the
gateway:

* Strict field allowlist -> an authority/executor/approval/adapter/callable
  object can never be smuggled in, because only known scalar fields exist.
* Deterministic canonical JSON -> the same logical envelope always serializes
  to the same bytes (stable input_digest, stable claim key, reproducible).
* schema_version is explicit and unknown versions DROP_FAIL_CLOSED (no
  best-effort coercion of an unknown schema).
* Forbidden values (NaN, Infinity, bytes, callables, custom objects, pickles)
  are rejected at the type boundary.

This module is stdlib-only (no gateway, no network, no execution import).
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from .exceptions import EnvelopeValidationError, UnknownEnvelopeSchema

#: Canonical schema version for the current contract.  Readers must accept this
#: exact string and REJECT anything else (fail closed, never coerce).
ENVELOPE_SCHEMA_VERSION = "shadow-envelope/v1"

#: Bounded scalar types permitted inside the envelope (Phase 8.3 §8).
_SCALAR_TYPES = (str, int, bool, type(None))

#: Bounded max raw size (bytes) of a serialized envelope.
DEFAULT_MAX_ENVELOPE_BYTES = 64 * 1024

#: Bounded max depth of nested containers (fixed, no unbounded recursion).
MAX_CONTAINER_DEPTH = 6

#: Bounded max items in the sanitized payload.
MAX_PAYLOAD_KEYS = 128

#: allowed string keys = max length bound (prevents pathological keys).
_MAX_KEY_LEN = 128

#: bound string value length (envelope is bounded by design).
_MAX_STR_LEN = 8192

#: A bounded denylist of field NAMES that can never denote secrets / authority /
#: execution anywhere in an envelope (top-level or inside sanitized_payload).
#: Approved / execute / apply / promote / override are authority-execution
#: words -> rejected so an envelope can never look like a grant.
FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "authorization", "auth", "cookie", "cookies", "token", "tokens",
        "password", "passwd", "secret", "credential", "credentials",
        "api_key", "apikey", "access_key", "private_key", "session_id",
        "approved", "approve", "grant", "granted", "execute", "exec", "run",
        "apply", "promote", "override", "replace_production", "promote_shadow",
        "authority", "executor", "adapter", "pickle", "callable",
    }
)

_FIELD_NAME_RE = re.compile(r"^[a-zA-Z0-9_]{1,%d}$" % _MAX_KEY_LEN)


def _is_secret_like(name: str) -> bool:
    """True if a field name is reserved (never accepted as envelope data)."""
    return name in FORBIDDEN_FIELD_NAMES or "token" in name.lower() \
        or "secret" in name.lower() or "key" in name.lower()


def _check_field_name(name: str, where: str) -> None:
    if not isinstance(name, str) or not _FIELD_NAME_RE.match(name):
        raise EnvelopeValidationError(f"{where}: invalid field name {name!r}")
    if _is_secret_like(name):
        raise EnvelopeValidationError(f"{where}: forbidden field name {name!r}")


def _finite_float(value: object) -> bool:
    return isinstance(value, float) and math.isfinite(value)


def _check_scalar(value: object, where: str) -> None:
    if isinstance(value, _SCALAR_TYPES):
        if isinstance(value, str) and len(value) > _MAX_STR_LEN:
            raise EnvelopeValidationError(f"{where}: string too large")
        if isinstance(value, bool):
            return
        if isinstance(value, int):
            # ~128-bit bound, prevents absurd ints from leaking into c14n.
            if not (-(2**127) <= value < 2**127):
                raise EnvelopeValidationError(f"{where}: int out of bound")
            return
        return
    if _finite_float(value):
        return
    # bytes / bytearray / NaN / Infinity / callable / module / class /
    # dataclass / file handle / custom object / ReferenceType -> reject.
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise EnvelopeValidationError(f"{where}: non-finite float forbidden")
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise EnvelopeValidationError(f"{where}: bytes are not allowed")
    if callable(value):
        raise EnvelopeValidationError(f"{where}: callable is forbidden")
    raise EnvelopeValidationError(
        f"{where}: unsupported value type {type(value).__name__!s}"
    )


def _sanitize_hashable_value(value: object, where: str) -> None:
    """Validate a single payload value (scalar or bounded list of scalars)."""
    _check_scalar(value, where)


def _validate_payload(payload: Mapping[str, object]) -> None:
    if not isinstance(payload, dict):
        raise EnvelopeValidationError("sanitized_payload must be a dict")
    if len(payload) > MAX_PAYLOAD_KEYS:
        raise EnvelopeValidationError("sanitized_payload too many keys")
    for k, v in payload.items():
        _check_field_name(k, "sanitized_payload")
        _check_scalar(v, f"sanitized_payload[{k!r}]")


@dataclass(frozen=True, slots=True)
class ProductionShadowEnvelopeV1:
    """Canonical immutable shadow envelope (the one-way production emit)."""

    #: official contract version — reader must reject anything else.
    schema_version: str
    event_id: str
    source_request_id: str
    tenant_id: str
    user_id: str
    request_kind: str
    sanitized_payload: Mapping[str, object] = field(default_factory=dict)
    input_digest: str = ""
    production_timestamp: float = 0.0
    trace_id: str = ""
    source_runtime_version: str = ""
    baseline_version: str = "1.3.6"

    # -- construction / validation ----------------------------------------

    def __post_init__(self) -> None:
        _require_nstr("event_id", self.event_id)
        _require_nstr("source_request_id", self.source_request_id)
        _require_nstr("tenant_id", self.tenant_id)
        _require_nstr("user_id", self.user_id)
        _require_nstr("request_kind", self.request_kind)
        if self.input_digest:
            _require_nstr("input_digest", self.input_digest)
        if self.baseline_version:
            _require_nstr("baseline_version", self.baseline_version)
        if not isinstance(self.production_timestamp, float) or not _finite_float(
            self.production_timestamp
        ):
            raise EnvelopeValidationError("production_timestamp must be a finite float")
        _validate_payload(self.sanitized_payload)

    # -- deterministic serialization (Phase 8.3 §8) -------------------------

    def to_canonical_dict(self) -> dict[str, object]:
        """Schema-stable, key-ordered, value-bounded mapping (no raw objs)."""
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "source_request_id": self.source_request_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "request_kind": self.request_kind,
            "sanitized_payload": dict(self.sanitized_payload),
            "input_digest": self.input_digest,
            "production_timestamp": float(self.production_timestamp),
            "trace_id": self.trace_id,
            "source_runtime_version": self.source_runtime_version,
            "baseline_version": self.baseline_version,
        }

    def to_bytes(self) -> bytes:
        """Deterministic canonical bytes (stable digest/claim key), no pickle."""
        try:
            raw = json.dumps(
                self.to_canonical_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        except (ValueError, TypeError) as exc:  # pragma: no cover - defensive
            raise EnvelopeValidationError(f"envelope not deterministically serializable: {exc}")
        if len(raw) > DEFAULT_MAX_ENVELOPE_BYTES:
            raise EnvelopeValidationError("envelope exceeds MAX_ENVELOPE_BYTES")
        return raw


def _require_nstr(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EnvelopeValidationError(f"{name} must be a non-empty string")
    if len(value) > _MAX_STR_LEN:
        raise EnvelopeValidationError(f"{name} exceeds max length")


@dataclass(frozen=True, slots=True)
class EnvelopeParseResult:
    """Outcome of parsing raw bytes: either a valid envelope or a rejection."""

    envelope: ProductionShadowEnvelopeV1 | None = None
    status: str = "INVALID"  # VALID | INVALID | UNKNOWN_SCHEMA
    reason: str = ""


def parse_envelope(raw: bytes) -> EnvelopeParseResult:
    """Strict parse of raw one-way bytes -> deterministic, fail-closed."""
    if isinstance(raw, (bytearray, memoryview)) or not isinstance(raw, bytes):
        return EnvelopeParseResult(status="INVALID", reason="not bytes input")
    if len(raw) == 0:
        return EnvelopeParseResult(status="INVALID", reason="empty envelope")
    if len(raw) > DEFAULT_MAX_ENVELOPE_BYTES:
        return EnvelopeParseResult(status="INVALID", reason="oversized envelope")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return EnvelopeParseResult(status="INVALID", reason=f"malformed json: {exc}")
    if not isinstance(parsed, dict):
        return EnvelopeParseResult(status="INVALID", reason="envelope must be a JSON object")

    sv = parsed.get("schema_version")
    if sv != ENVELOPE_SCHEMA_VERSION:
        return EnvelopeParseResult(status="UNKNOWN_SCHEMA", reason=f"unknown schema {sv!r}")

    # Strict top-level field allowlist: unknown keys -> reject (blocks
    # authority/execute/approve/secret drift at the envelope boundary).
    allowed = {
        "schema_version", "event_id", "source_request_id", "tenant_id", "user_id",
        "request_kind", "sanitized_payload", "input_digest", "production_timestamp",
        "trace_id", "source_runtime_version", "baseline_version",
    }
    unknown = set(parsed) - allowed
    if unknown:
        return EnvelopeParseResult(status="INVALID",
                                    reason=f"unknown top-level fields: {sorted(unknown)}")

    try:
        envelope = ProductionShadowEnvelopeV1(
            schema_version=ENVELOPE_SCHEMA_VERSION,
            event_id=parsed["event_id"],
            source_request_id=parsed["source_request_id"],
            tenant_id=parsed["tenant_id"],
            user_id=parsed["user_id"],
            request_kind=parsed["request_kind"],
            sanitized_payload=parsed.get("sanitized_payload", {}),
            input_digest=parsed.get("input_digest", ""),
            production_timestamp=float(parsed.get("production_timestamp", 0.0)),
            trace_id=parsed.get("trace_id", ""),
            source_runtime_version=parsed.get("source_runtime_version", ""),
            baseline_version=parsed.get("baseline_version", "1.3.6"),
        )
    except (EnvelopeValidationError, KeyError, TypeError, ValueError) as exc:
        return EnvelopeParseResult(status="INVALID", reason=f"validation error: {exc}")

    # round-trip canonical stability check: an envelope that does NOT serialize
    # back to its canonical form is not deterministic -> reject.
    if envelope.to_bytes() != raw and envelope.to_bytes() != raw.strip():
        return EnvelopeParseResult(status="INVALID", reason="non-canonical (not round-trip stable)")

    return EnvelopeParseResult(envelope=envelope, status="VALID")


def new_event_id() -> str:
    return uuid.uuid4().hex


def default_timestamp() -> float:
    return float(time.time())


__all__ = [
    "DEFAULT_MAX_ENVELOPE_BYTES",
    "ENVELOPE_SCHEMA_VERSION",
    "EnvelopeParseResult",
    "FORBIDDEN_FIELD_NAMES",
    "ProductionShadowEnvelopeV1",
    "default_timestamp",
    "new_event_id",
    "parse_envelope",
]