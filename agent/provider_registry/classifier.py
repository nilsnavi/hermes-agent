"""ProviderErrorClassifier — unified error classification for the registry.

Compatibility layer: the existing classifier is agent/error_classifier.py
(FailoverReason, used by the retry loop in run_agent/conversation_loop).
This module adds the registry-facing taxonomy (ProviderErrorClass) and
MUST be consulted first for the critical distinction demanded by Sprint 0.4:

    OpenRouter 403 "Access denied by security policy"
        → WAF_BLOCKED / GEO_BLOCKED,  NEVER AUTH_INVALID

Existing _AUTH_PATTERNS in error_classifier.py contains "access denied" /
"forbidden", so WAF/GEO markers are matched BEFORE auth markers here.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .domain import AvailabilityReason, CircuitImpact


class ProviderErrorClass(enum.Enum):
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    AUTH_MISSING = "AUTH_MISSING"
    AUTH_UNSUPPORTED = "AUTH_UNSUPPORTED"

    GEO_BLOCKED = "GEO_BLOCKED"
    WAF_BLOCKED = "WAF_BLOCKED"

    MODEL_NOT_SUPPORTED = "MODEL_NOT_SUPPORTED"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"

    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    NETWORK_DNS = "NETWORK_DNS"
    NETWORK_CONNECT = "NETWORK_CONNECT"

    SERVER_ERROR = "SERVER_ERROR"
    BAD_REQUEST = "BAD_REQUEST"

    UNKNOWN = "UNKNOWN"


@dataclass
class Classification:
    error_class: ProviderErrorClass
    retryable: bool = True
    circuit_impact: CircuitImpact = CircuitImpact.LOW
    availability_reason: AvailabilityReason = AvailabilityReason.UNKNOWN
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "errorClass": self.error_class.value,
            "retryable": self.retryable,
            "circuitImpact": self.circuit_impact.value,
            "availabilityReason": self.availability_reason.value,
            "detail": self.detail,
        }


# ── Markers (checked in priority order) ──────────────────────────────────

# Geo blocks are applied by the platform BEFORE credential validation, so a
# geo-blocked response says NOTHING about the key.
_GEO_MARKERS = [
    "unsupported_country_region_territory",   # OpenAI
    "user location is not supported",          # Google
    "location is not supported",
    "not available in your country",
    "not available in your region",
    "not supported in your region",
    "country region",
    "geographical restrictions",
    "request not allowed",                      # Anthropic geo 403
    "geoblocked",
    "geo-blocked",
    "geo blocked",
    "inference-api access restricted",          # nous-style geo wording
]

# WAF / platform policy blocks — identical with and without a key.
_WAF_MARKERS = [
    "access denied by security policy",         # OpenRouter WAF
    "access denied",                             # Cloudflare / generic WAF
    "cloudflare",
    "cf-ray",
    "security policy",
    "blocked by security",
    "waf",
    "forbidden by a security policy",
    "web application firewall",
]

# Auth markers (only after GEO/WAF did not match).
_AUTH_INVALID_MARKERS = [
    "invalid api key",
    "invalid_api_key",
    "api key invalid",
    "api key is invalid",
    "неверный api ключ",
    "неверный ключ",
    "невалидный ключ",
    "invalid credential",
    "invalid credentials",
    "authentication failed",
    "authentication error",
    "unauthorized client",                       # agentrouter.org
    "unauthorized_client",
    "invalid token",                             # generic (see expired below)
    "token invalid",
    "token revoked",
    "token is invalid",
    "bad credentials",
    "incorrect api key",
]

_AUTH_EXPIRED_MARKERS = [
    "token expired",
    "token has expired",
    "token is expired",
    "expired token",
    "access token expired",
    "refresh token expired",
    "expired",
    "expiration",
    "has expired",
    "oauth token expired",
]

_AUTH_UNSUPPORTED_MARKERS = [
    "unsupported auth",
    "unsupported authentication",
    "auth scheme",
    "not a valid copilot",
    "copilot token",
    "pat is not supported",
    "only oauth",
]

_MODEL_NOT_FOUND_MARKERS = [
    "model not found",
    "model_not_found",
    "is not a valid model",
    "invalid model",
    "does not exist",
    "no such model",
    "unknown model",
    "model does not exist",
    "no endpoints found that support tool use",
]

_MODEL_NOT_SUPPORTED_MARKERS = [
    "model not supported",
    "model_not_supported",
    "unsupported model",
    "not supported for this provider",
    "model not supported on free tier",
    "model_not_supported_on_free_tier",
    "not available on the free tier",
    "provider model mismatch",
    "provider_model_mismatch",
    "does not support model",
    "model is not supported",
]

_QUOTA_MARKERS = [
    "insufficient credits",
    "insufficient_quota",
    "insufficient balance",
    "credit balance",
    "credits exhausted",
    "credits have been exhausted",
    "no usable credits",
    "top up your credits",
    "payment required",
    "billing hard limit",
    "exceeded your current quota",
    "account is deactivated",
    "out of extra usage",
    "out of funds",
    "balance_depleted",
    "quota exceeded",
    "quota_exceeded",
    "not available on the free tier",
]

_RATE_LIMIT_MARKERS = [
    "rate limit",
    "rate_limit",
    "too many requests",
    "throttled",
    "throttling",
    "requests per minute",
    "tokens per minute",
    "requests per day",
    "try again in",
    "please retry after",
    "resource_exhausted",
    "too many concurrent requests",
]

_TIMEOUT_MARKERS = [
    "timed out",
    "turn timed out",
    "request timed out",
    "deadline exceeded",
    "operation timed out",
    "upstream timed out",
    "read timeout",
    "connect timeout",
    "pool timeout",
    "timeout",
]

_DNS_MARKERS = [
    "getaddrinfo",
    "name resolution",
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "dns",
]

_CONNECT_MARKERS = [
    "connection refused",
    "connection reset",
    "connection error",
    "connecterror",
    "remote protocol error",
    "broken pipe",
    "connection aborted",
    "connection closed",
    "server disconnected",
    "unexpected eof",
    "peer closed connection",
    "network connection lost",
    "cannot connect",
    "failed to connect",
    "no route to host",
    "network is unreachable",
]

_TRANSPORT_ERROR_TYPES = frozenset({
    "ReadTimeout", "ConnectTimeout", "PoolTimeout",
    "ConnectError", "RemoteProtocolError",
    "ConnectionError", "ConnectionResetError",
    "ConnectionAbortedError", "BrokenPipeError",
    "TimeoutError", "ReadError", "ServerDisconnectedError",
    "APIConnectionError", "APITimeoutError",
    "requests.exceptions.Timeout", "requests.exceptions.ConnectionError",
    "socket.timeout",
})

# ── Helpers ──────────────────────────────────────────────────────────────

def _has_any(text: str, markers: list) -> bool:
    low = text.lower()
    return any(m in low for m in markers)


def _strip_ws(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text or "").strip()


# ── Classifier ───────────────────────────────────────────────────────────

# Mapping used to derive availability reason + impact once class is known.
_CLASS_TO_REASON = {
    ProviderErrorClass.AUTH_INVALID: AvailabilityReason.AUTH,
    ProviderErrorClass.AUTH_EXPIRED: AvailabilityReason.AUTH,
    ProviderErrorClass.AUTH_MISSING: AvailabilityReason.AUTH,
    ProviderErrorClass.AUTH_UNSUPPORTED: AvailabilityReason.UNSUPPORTED_AUTH,
    ProviderErrorClass.GEO_BLOCKED: AvailabilityReason.GEO_BLOCKED,
    ProviderErrorClass.WAF_BLOCKED: AvailabilityReason.WAF_BLOCKED,
    ProviderErrorClass.MODEL_NOT_SUPPORTED: AvailabilityReason.MODEL_UNAVAILABLE,
    ProviderErrorClass.MODEL_NOT_FOUND: AvailabilityReason.MODEL_UNAVAILABLE,
    ProviderErrorClass.RATE_LIMITED: AvailabilityReason.RATE_LIMIT,
    ProviderErrorClass.QUOTA_EXCEEDED: AvailabilityReason.QUOTA,
    ProviderErrorClass.NETWORK_TIMEOUT: AvailabilityReason.NETWORK,
    ProviderErrorClass.NETWORK_DNS: AvailabilityReason.NETWORK,
    ProviderErrorClass.NETWORK_CONNECT: AvailabilityReason.NETWORK,
    ProviderErrorClass.SERVER_ERROR: AvailabilityReason.UNKNOWN,
    ProviderErrorClass.BAD_REQUEST: AvailabilityReason.CONFIGURATION,
    ProviderErrorClass.UNKNOWN: AvailabilityReason.UNKNOWN,
}

#: permanent classes → routing disabled directly, no circuit churn (Sprint §9)
PERMANENT_CLASSES = frozenset({
    ProviderErrorClass.AUTH_INVALID,
    ProviderErrorClass.AUTH_EXPIRED,
    ProviderErrorClass.AUTH_MISSING,
    ProviderErrorClass.AUTH_UNSUPPORTED,
    ProviderErrorClass.GEO_BLOCKED,
    ProviderErrorClass.WAF_BLOCKED,
    ProviderErrorClass.QUOTA_EXCEEDED,
})


class ProviderErrorClassifier:
    """Classifies provider API errors into the registry taxonomy."""

    def __init__(self) -> None:
        pass

    def classify(
        self,
        provider: str = "",
        http_status: Optional[int] = None,
        message: str = "",
        error_type: str = "",
        operation: str = "inference",
    ) -> Classification:
        """Classify an error.

        Priority: GEO → WAF → AUTH_EXPIRED → AUTH_INVALID → AUTH_UNSUPPORTED
        → MODEL → QUOTA → RATE → SERVER → NETWORK → BAD_REQUEST → UNKNOWN.
        """
        text = _strip_ws(message)
        etype = (error_type or "").strip()
        status = http_status

        # 1) Geo block — platform-level, before anything else.
        if _has_any(text, _GEO_MARKERS):
            return self._mk(ProviderErrorClass.GEO_BLOCKED, detail=text[:200])
        if status in (400, 403) and "location" in text and "support" in text:
            return self._mk(ProviderErrorClass.GEO_BLOCKED, detail=text[:200])

        # 2) WAF / security-policy block — same with and without key.
        if _has_any(text, _WAF_MARKERS):
            return self._mk(ProviderErrorClass.WAF_BLOCKED, detail=text[:200])
        if status == 403 and "security" in text:
            return self._mk(ProviderErrorClass.WAF_BLOCKED, detail=text[:200])

        # 3) Auth — expired checked before invalid.
        if _has_any(text, _AUTH_EXPIRED_MARKERS):
            return self._mk(ProviderErrorClass.AUTH_EXPIRED, detail=text[:200])
        if status in (401, 403):
            if _has_any(text, _AUTH_UNSUPPORTED_MARKERS):
                return self._mk(ProviderErrorClass.AUTH_UNSUPPORTED, detail=text[:200])
            if _has_any(text, _AUTH_INVALID_MARKERS):
                return self._mk(ProviderErrorClass.AUTH_INVALID, detail=text[:200])
            if status == 401:
                # A bare 401 without a recognizable body is auth-invalid by
                # definition — an API rejected the credential.
                return self._mk(ProviderErrorClass.AUTH_INVALID, detail="401 without details")
            # 403 without WAF/geo/auth markers: ambiguous → UNKNOWN,
            # treated as permanent (never retry blindly).
            return Classification(
                error_class=ProviderErrorClass.UNKNOWN,
                retryable=False,
                circuit_impact=CircuitImpact.HIGH,
                availability_reason=AvailabilityReason.UNKNOWN,
                detail=text[:200],
            )

        # 4) Model errors.
        if _has_any(text, _MODEL_NOT_SUPPORTED_MARKERS):
            return self._mk(ProviderErrorClass.MODEL_NOT_SUPPORTED, detail=text[:200])
        if status == 404 or _has_any(text, _MODEL_NOT_FOUND_MARKERS):
            return self._mk(ProviderErrorClass.MODEL_NOT_FOUND, detail=text[:200])

        # 5) Billing / quota.
        if status == 402 or _has_any(text, _QUOTA_MARKERS):
            return self._mk(ProviderErrorClass.QUOTA_EXCEEDED, detail=text[:200])

        # 6) Rate limit.
        if status == 429 or _has_any(text, _RATE_LIMIT_MARKERS):
            return Classification(
                error_class=ProviderErrorClass.RATE_LIMITED,
                retryable=True,
                circuit_impact=CircuitImpact.LOW,
                availability_reason=AvailabilityReason.RATE_LIMIT,
                detail=text[:200],
            )

        # 7) Server errors.
        if status is not None and 500 <= status < 600:
            return Classification(
                error_class=ProviderErrorClass.SERVER_ERROR,
                retryable=True,
                circuit_impact=CircuitImpact.LOW,
                availability_reason=AvailabilityReason.UNKNOWN,
                detail=text[:200],
            )

        # 8) Transport / network.
        if _has_any(text, _TIMEOUT_MARKERS) or etype in _TRANSPORT_ERROR_TYPES:
            if _has_any(text, _DNS_MARKERS):
                return self._mk(ProviderErrorClass.NETWORK_DNS, detail=text[:200])
            if _has_any(text, _TIMEOUT_MARKERS) or etype in {"ReadTimeout", "ConnectTimeout", "PoolTimeout", "APITimeoutError", "TimeoutError", "socket.timeout"}:
                return Classification(
                    error_class=ProviderErrorClass.NETWORK_TIMEOUT,
                    retryable=True,
                    circuit_impact=CircuitImpact.LOW,
                    availability_reason=AvailabilityReason.NETWORK,
                    detail=text[:200],
                )
            return Classification(
                error_class=ProviderErrorClass.NETWORK_CONNECT,
                retryable=True,
                circuit_impact=CircuitImpact.LOW,
                availability_reason=AvailabilityReason.NETWORK,
                detail=text[:200],
            )
        if _has_any(text, _DNS_MARKERS):
            return self._mk(ProviderErrorClass.NETWORK_DNS, detail=text[:200])
        if _has_any(text, _CONNECT_MARKERS):
            return Classification(
                error_class=ProviderErrorClass.NETWORK_CONNECT,
                retryable=True,
                circuit_impact=CircuitImpact.LOW,
                availability_reason=AvailabilityReason.NETWORK,
                detail=text[:200],
            )

        # 9) Bad request.
        if status is not None and 400 <= status < 500:
            return Classification(
                error_class=ProviderErrorClass.BAD_REQUEST,
                retryable=False,
                circuit_impact=CircuitImpact.LOW,
                availability_reason=AvailabilityReason.CONFIGURATION,
                detail=text[:200],
            )

        return Classification(
            error_class=ProviderErrorClass.UNKNOWN,
            retryable=True,
            circuit_impact=CircuitImpact.LOW,
            availability_reason=AvailabilityReason.UNKNOWN,
            detail=text[:200],
        )

    def _mk(self, cls: ProviderErrorClass, detail: str = "") -> Classification:
        permanent = cls in PERMANENT_CLASSES
        return Classification(
            error_class=cls,
            retryable=not permanent,
            circuit_impact=CircuitImpact.HIGH if permanent else CircuitImpact.LOW,
            availability_reason=_CLASS_TO_REASON.get(cls, AvailabilityReason.UNKNOWN),
            detail=detail,
        )
