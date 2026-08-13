"""Payload redaction + canonical hashing (Sprint 1.0.3).

Structured scrubber for dict/list payloads before they touch the DB:
API keys, tokens, passwords, secrets — values replaced with a marker,
recursively, key match is case-insensitive EXACT (so ``token_count`` and
``session_id`` stay intact). Key list is the project's own
``agent.redact._SENSITIVE_BODY_KEYS`` (+ ``cookie``) — one source of truth.
"""

import hashlib
import json
from typing import Any, Dict, FrozenSet, Optional

from agent.redact import _SENSITIVE_BODY_KEYS

REDACTED = "[REDACTED]"

# Project list + cookie (spec §26 minimum list is a subset of this).
_SENSITIVE_KEYS: FrozenSet[str] = _SENSITIVE_BODY_KEYS | frozenset({"cookie"})

# Sprint 1.0.6.2 §60 hardening: common secret-bearing key names missing
# from the project list, plus a NORMALIZED matcher so camelCase/snake_case
# variants (apiToken / API_TOKEN / auth_token …) are caught WITHOUT
# over-redacting generic fields (token_count / session_id / key_count).
_EXTENDED_KEYS: FrozenSet[str] = _SENSITIVE_KEYS | frozenset({
    "api_token", "auth_token", "session_token",
})


def _normalize_key(key: Any) -> str:
    """Lowercase + strip non-alphanumerics: ``apiToken`` → ``apitoken``."""
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


_NORMALIZED_SENSITIVE: FrozenSet[str] = frozenset(
    _normalize_key(k) for k in _EXTENDED_KEYS
)


def is_sensitive_key(key: Any) -> bool:
    """Exact case-insensitive match OR normalized (alnum) match.

    ``token_count`` → ``tokencount`` ∉ set → False (survives).
    ``apiToken``  → ``apitoken`` ∈ set → True (redacted).
    """
    k = str(key)
    return k.lower() in _EXTENDED_KEYS or _normalize_key(k) in _NORMALIZED_SENSITIVE


def scrub(value: Any) -> Any:
    """Deep-copy *value* with sensitive values replaced by REDACTED.

    Dict keys are matched via :func:`is_sensitive_key` (case-insensitive
    exact + normalized); lists/tuples are scrubbed element-wise; scalars
    pass through.
    """
    if isinstance(value, dict):
        return {
            k: (REDACTED if is_sensitive_key(k) else scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    """Stable canonical JSON: sorted keys, unicode kept, no whitespace."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(value: Any) -> str:
    """SHA-256 of the canonical JSON of *value* (scrub BEFORE hashing)."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def scrub_and_hash(value: Any) -> tuple:
    """Return ``(scrubbed_value, sha256_of_scrubbed)`` — one call pattern."""
    safe = scrub(value)
    return safe, sha256_hex(safe)


def compute_input_hash(arguments: Optional[Dict]) -> str:
    """Canonical SHA-256 of SCRUBBED tool arguments (Sprint 1.0.5/1.0.6).

    Secrets are redacted BEFORE hashing — the digest cannot leak them, and
    a hash never replaces redaction (the persisted event carries only the
    scrubbed payload + this digest).
    """
    _, digest = scrub_and_hash(arguments if arguments is not None else {})
    return digest


def compute_output_hash(result_dict: Any) -> str:
    """Canonical SHA-256 of the SCRUBBED tool result dict."""
    return sha256_hex(scrub(result_dict))


def idempotency_key(run_id: str, step_id: str, input_hash: str) -> str:
    """Deterministic per-step-attempt key: SHA-256(run_id|step_id|input_hash).

    Same canonical input (post-restart) → same key; different input →
    different key. Secret-free by construction (input_hash is scrubbed).
    """
    return hashlib.sha256(
        f"{run_id}|{step_id}|{input_hash}".encode("utf-8")
    ).hexdigest()


def scrub_nested(payload: Any, sensitive_keys: Optional[FrozenSet[str]] = None) -> Any:
    """Scrub with an explicit key set (overrides the default)."""

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (REDACTED if is_sensitive_key(k) else _walk(v))
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [_walk(v) for v in value]
        return value

    return _walk(payload)
