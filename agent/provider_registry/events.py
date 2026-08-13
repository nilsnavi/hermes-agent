"""Structured registry events (Sprint 0.4 §13).

Every event carries ONLY whitelisted fields — never keys, tokens,
authorization headers, full response bodies, or secret-bearing query
params. A defensive scrubber drops anything that looks secret even if a
caller passes it in metadata.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from .domain import REGISTRY_EVENTS

logger = logging.getLogger("hermes.provider_registry")

#: field names that are never allowed to leave the process
_FORBIDDEN_KEYS = frozenset({
    "key", "api_key", "apikey", "token", "access_token", "refresh_token",
    "authorization", "auth", "secret", "password", "passwd", "credential",
    "credentials", "bearer", "x-api-key", "proxy_auth",
})

_SECRET_KEY_HINTS = ("key", "token", "secret", "auth", "password", "bearer", "credential")

#: whitelisted event payload fields
_ALLOWED_FIELDS = (
    "timestamp", "provider", "event", "status", "httpStatus", "errorClass",
    "durationMs", "detail", "healthStatus", "authStatus", "availabilityReason",
    "routingEligible", "circuitState", "providerCount", "checked",
    "operation", "mode",
    # Sprint 0.7 §9/§10: integration lifecycle fields (never secrets —
    # values are checked by _is_secret_key on the key name only, and
    # reason/endpoint texts must not contain credentials by policy).
    "integration", "attempt", "nextRetryAt", "suppressed", "reason",
)


def _is_secret_key(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in _SECRET_KEY_HINTS)


def scrub(obj: Any) -> Any:
    """Deep-scrub a payload: replace secret-looking values with '***'."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_secret_key(str(k)):
                out[k] = "***"
            else:
                out[k] = scrub(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


def emit(
    event: str,
    provider: str = "",
    status: str = "",
    http_status: Optional[int] = None,
    error_class: str = "",
    duration_ms: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit one structured registry event to the 'hermes.provider_registry' logger."""
    if event not in REGISTRY_EVENTS:
        event = "provider.unknown"
    payload: Dict[str, Any] = {
        "timestamp": time.time(),
        "provider": provider,
        "event": event,
        "status": status,
        "httpStatus": http_status,
        "errorClass": error_class,
        "durationMs": duration_ms,
    }
    if extra:
        clean = scrub(extra)
        for k in list(clean.keys()):
            if k in _ALLOWED_FIELDS and k not in payload:
                payload[k] = clean[k]
            elif k in payload:
                payload[k] = clean[k]
    # final defensive pass — drop anything that slipped through as secret
    final = {k: v for k, v in payload.items() if not _is_secret_key(str(k))}
    logger.info("provider.event %s", json.dumps(final, ensure_ascii=False, sort_keys=True))
