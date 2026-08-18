"""Safe query normalization (§6) — literal substring contract.

The query is the ONLY user-controlled string that reaches adapters.
It is normalized and validated here, then treated strictly as a
literal substring/token by every adapter. No regex interpretation,
no shell syntax, no path semantics, no SQL fragments.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

from .models import MAX_QUERY_LENGTH, SearchError, SearchErrorCode

#: Control characters (incl. NUL, ANSI escapes) are rejected outright.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
#: Whitespace run for collapse.
_WS_RE = re.compile(r"\s+")


def normalize_query(raw: object) -> str:
    """Unicode NFC -> casefold -> trim -> collapse whitespace.

    Returns the normalized literal. Raises :class:`SearchError`
    (INVALID_QUERY) for non-text, empty, oversized, or control-char
    input — the adapter never sees an unvalidated query.
    """
    if raw is None:
        raise SearchError(
            SearchErrorCode.INVALID_QUERY, "query is required")
    if not isinstance(raw, str):
        raise SearchError(
            SearchErrorCode.INVALID_QUERY,
            f"query must be text, got {type(raw).__name__}")
    norm = unicodedata.normalize("NFC", raw)
    if _CONTROL_RE.search(norm):
        raise SearchError(
            SearchErrorCode.INVALID_QUERY,
            "query contains control characters")
    norm = norm.casefold()
    norm = norm.strip()
    norm = _WS_RE.sub(" ", norm)
    if not norm:
        raise SearchError(
            SearchErrorCode.INVALID_QUERY, "query is empty")
    if len(norm) > MAX_QUERY_LENGTH:
        raise SearchError(
            SearchErrorCode.INVALID_QUERY,
            f"query exceeds {MAX_QUERY_LENGTH} chars")
    return norm


def validate_query(raw: object) -> Tuple[bool, Optional[str]]:
    """Non-raising variant: ``(ok, error_message_or_None)``.

    Used by the router's shadow eval so an INVALID_QUERY never
    bubbles as an exception inside enforcement decisions.
    """
    try:
        normalize_query(raw)
        return True, None
    except SearchError as exc:
        return False, exc.message


#: Secret-sensitive terms — a query asking for credentials is a DENY
#: candidate regardless of source (§18 N1/N2/N7). Literal keyword
#: scan, deliberately conservative (over-blocking a keyword is safer
#: than leaking a secret; these are not "safe operational" subjects).
_SECRET_QUERY_TERMS = (
    "пароль", "password", "пароля", "пароли",
    "api_key", "apikey", "api key",
    "openai_api_key", "token", "secret",
    "authorization", "bearer", "cookie",
    "credentials", "credential", "учётные", "учетные",
    "приватный ключ", "private key",
    "/etc/shadow", "shadow file",
)


def is_secret_query(norm_query: str) -> bool:
    """True when the normalized query asks for credential material.

    Prevents candidate V2 for secret-hunting requests even when the
    intent classifies as SEARCH_READ (§18). Runs on the NORMALIZED
    literal (no regex, no shell syntax from the user is reachable).
    """
    q = (norm_query or "").casefold()
    return any(term in q for term in _SECRET_QUERY_TERMS)


def escape_like_literal(query: str) -> str:
    """Escape a literal for SQL LIKE — user input stays a VALUE.

    ``%`` ``_`` and the escape char itself are quoted so the query
    can never act as a pattern. Callers use
    ``... LIKE ? ESCAPE '\\' ...`` with this value.
    """
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
