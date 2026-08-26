"""Immutable production->shadow envelope (Phase 8 §4).

``ProductionShadowEnvelope`` is the ONLY object that crosses from the production
path into the shadow runtime. It is a minimal, immutable, sanitized snapshot and
carries NO credentials, tokens, cookies, Authorization, raw secrets, executor
handles, adapter references, approval objects or capability grants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _req(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ProductionShadowEnvelope:
    """Bounded metadata + sanitized task payload; one-way data (DATA ONLY)."""

    source_request_id: str
    tenant_id: str
    user_id: str
    request_kind: str
    input_digest: str
    sanitized_context: tuple[str, ...]  # only canonicalized strings (bounded)
    production_timestamp: float
    baseline_version: str
    trace_id: str

    def __post_init__(self) -> None:
        for name in (
            "source_request_id", "tenant_id", "user_id", "request_kind",
            "input_digest", "baseline_version", "trace_id",
        ):
            object.__setattr__(self, name, _req(name, getattr(self, name)))
        if (
            not isinstance(self.sanitized_context, tuple)
            or len(self.sanitized_context) > 8
        ):
            raise ValueError("sanitized_context must be a bounded tuple (<=8 items)")
        for item in self.sanitized_context:
            if not isinstance(item, str) or len(item) > 512:
                raise ValueError("context items must be short canonical strings")
        if not isinstance(self.production_timestamp, (int, float)) or not float(self.production_timestamp) >= 0:
            raise ValueError("production_timestamp must be a non-negative number")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_request_id": self.source_request_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "request_kind": self.request_kind,
            "input_digest": self.input_digest,
            "sanitized_context": self.sanitized_context,
            "production_timestamp": self.production_timestamp,
            "baseline_version": self.baseline_version,
            "trace_id": self.trace_id,
        }


# Forbidden content markers: an envelope must NEVER carry these.
FORBIDDEN_SUBSTRINGS = (
    "authorization", "cookie", "token", "secret", "password", "apikey",
    "api_key", "bearer", "executor", "adapter", "grant", "credential",
)


def assert_no_forbidden_content(envelope: ProductionShadowEnvelope) -> None:
    """Deny envelopes that smuggle authority/secret/executor content (incl. context items)."""
    for key, value in envelope.to_dict().items():
        if isinstance(value, str):
            if any(f in value.lower() for f in FORBIDDEN_SUBSTRINGS):
                raise ValueError(f"envelope field {key!r} contains forbidden content")
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, str) and any(f in item.lower() for f in FORBIDDEN_SUBSTRINGS):
                    raise ValueError(f"envelope field {key!r} context item contains forbidden content")


# One-way flow: production -> shadow ONLY. There is deliberately NO method that
# could return a shadow result into the production path.
__all__ = [
    "FORBIDDEN_SUBSTRINGS",
    "ProductionShadowEnvelope",
    "assert_no_forbidden_content",
]