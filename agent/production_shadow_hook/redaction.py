"""Data minimization for the production shadow hook (Phase 8 §5).

Before enqueue the hook: drops unknown fields, applies a field allowlist, bounds
sizes, and redacts secret-bearing keys. Only metadata + a bounded sanitized task
payload is emitted -- never the full raw request by default. Unknown field DROP.
"""

from __future__ import annotations

from typing import Any, Mapping

# Secret-key markers: if a raw field name hints at a secret, it is DROPPED.
_SECRET_KEY_MARKERS = ("token", "secret", "password", "apikey", "api_key",
                       "authorization", "cookie", "credential", "bearer")
# Only these fields are permitted into the sanitized context (field allowlist).
ALLOWED_CONTEXT_KEYS = frozenset({
    "request_kind", "intent", "task_summary", "model", "language", "channel",
    "message_type", "step", "resource",
})
MAX_FIELD_LENGTH = 512
MAX_CONTEXT_ITEMS = 8


def _looks_secret_key(key: str) -> bool:
    k = key.lower()
    return any(marker in k for marker in _SECRET_KEY_MARKERS)


def _canonicalize(value: Any, key: str) -> str | None:
    """Yield a bounded canonical string for an allowed value, else None (drop)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return None  # drop non-finite
        return str(value)
    if isinstance(value, str):
        if len(value) > MAX_FIELD_LENGTH:
            return value[:MAX_FIELD_LENGTH]  # bound size
        return value
    return None  # drop objects/callables/containers automatically


def sanitize_context(raw: Mapping[str, Any]) -> tuple[str, ...]:
    """Bounded, sanitized, allowlisted context tuple (drop unknown/secret fields)."""
    out: list[str] = []
    for key, value in raw.items():
        if key not in ALLOWED_CONTEXT_KEYS:
            continue  # unknown field -> DROP (never copied)
        if _looks_secret_key(key):
            continue  # secret-bearing key -> DROP
        text = _canonicalize(value, key)
        if text is None:
            continue
        out.append(f"{key}={text}")
        if len(out) >= MAX_CONTEXT_ITEMS:
            break
    return tuple(out)


__all__ = ["ALLOWED_CONTEXT_KEYS", "MAX_CONTEXT_ITEMS", "sanitize_context"]