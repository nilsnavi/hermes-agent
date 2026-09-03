"""Recursive response sanitization for capability boundaries."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

from agent.redact import redact_sensitive_text


_SENSITIVE_KEYS = frozenset(
    {
        "token",
        "password",
        "secret",
        "authorization",
        "cookie",
        "set-cookie",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "credentials",
        "client_secret",
    }
)

_REDACTED = "[REDACTED]"
_MAX_DEPTH = 24


def _normalized_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_")


_NORMALIZED_SENSITIVE_KEYS = frozenset(
    _normalized_key(key) for key in _SENSITIVE_KEYS
)


def sanitize(value: Any, *, _depth: int = 0) -> Any:
    """Return a recursively sanitized representation.

    Sensitive mapping keys are removed from the trust boundary regardless of
    case or '-'/'_' spelling. Strings receive the existing Hermes redactor as
    defense-in-depth.
    """

    if _depth > _MAX_DEPTH:
        return "[MAX_DEPTH]"

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        return redact_sensitive_text(value, force=True)

    if is_dataclass(value) and not isinstance(value, type):
        return sanitize(asdict(value), _depth=_depth + 1)

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = _normalized_key(key)
            output_key = str(key)

            if normalized in _NORMALIZED_SENSITIVE_KEYS:
                result[output_key] = _REDACTED
            else:
                result[output_key] = sanitize(
                    item,
                    _depth=_depth + 1,
                )
        return result

    if isinstance(value, tuple):
        return tuple(
            sanitize(item, _depth=_depth + 1)
            for item in value
        )

    if isinstance(value, list):
        return [
            sanitize(item, _depth=_depth + 1)
            for item in value
        ]

    if isinstance(value, set | frozenset):
        return [
            sanitize(item, _depth=_depth + 1)
            for item in sorted(value, key=repr)
        ]

    # Unknown object types are not serialized by repr(), because arbitrary
    # repr implementations may expose credentials.
    return f"[UNSUPPORTED:{type(value).__name__}]"
