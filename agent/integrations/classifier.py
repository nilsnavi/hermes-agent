"""Integration error classification (Sprint 0.7 §8).

Maps raw failure text/exceptions to a stable taxonomy.  The canonical
Home Assistant failure — ``homeassistant.local:8123`` + ``Name or service
not known`` — must classify as DNS_FAILURE, never a generic traceback.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .domain import NON_RETRYABLE_CLASSES

# (regex, class) — ordered: first match wins.
_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"name or service not known", re.I), "DNS_FAILURE"),
    (re.compile(r"nodename nor servname", re.I), "DNS_FAILURE"),
    (re.compile(r"getaddrinfo failed", re.I), "DNS_FAILURE"),
    (re.compile(r"cannot connect to host", re.I), "DNS_FAILURE"),
    (re.compile(r"errno\s*-?2", re.I), "DNS_FAILURE"),
    (re.compile(r"errno\s*-?111|connection refused", re.I), "CONNECTION_REFUSED"),
    (re.compile(r"timed? ?out|timeout", re.I), "TIMEOUT"),
    (re.compile(r"\b401\b|invalid api key|authentication_error|bad credentials", re.I), "AUTH_INVALID"),
    (re.compile(r"\b403\b|forbidden|access denied|waf|geo[- ]?blocked", re.I), "HTTP_4XX"),
    (re.compile(r"\b404\b|\b429\b|too many requests|rate ?limit", re.I), "RATE_LIMIT"),
    (re.compile(r"\b5\d\d\b|server error|internal error", re.I), "HTTP_5XX"),
    (re.compile(r"misconfig|invalid config|not configured|missing token|no token", re.I), "MISCONFIGURED"),
]


def classify_error(text: Optional[Any]) -> str:
    """Classify a failure message/exception into an error class."""
    raw = "" if text is None else str(text)
    if not raw.strip():
        return "UNKNOWN"
    for pattern, cls in _RULES:
        if pattern.search(raw):
            return cls
    return "UNKNOWN"


def classify_exception(exc: BaseException) -> str:
    return classify_error(getattr(exc, "message", None) or str(exc))


def is_retryable(error_class: str) -> bool:
    """Permanent configuration/auth failures must not be retried often."""
    return error_class not in NON_RETRYABLE_CLASSES