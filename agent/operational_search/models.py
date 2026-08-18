"""Operational Search data models (Sprint 1.2.2 §4/§8/§13/§14).

Pure data contracts: request DTO, result projection, source enum,
time-window presets, resource bounds and the error taxonomy. No I/O
here — the engine owns all execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ── resource bounds (§13) ──────────────────────────────────────────

MAX_QUERY_LENGTH = 128
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_SUMMARY_LENGTH = 300
DEFAULT_TIMEOUT_SECONDS = 2.0
MAX_BYTES_PER_FILE = 512 * 1024  # bounded scan window per log file
MAX_SCAN_LINES = 4000
TIME_WINDOW_PRESETS: Dict[str, timedelta] = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
}
DEFAULT_TIME_WINDOW = "1h"


class SearchSource(str, Enum):
    """Allowed search sources (§4) — a closed enum, never user text."""

    GATEWAY_LOG = "GATEWAY_LOG"
    EVENTS = "EVENTS"
    SCHEDULER = "SCHEDULER"
    PROVIDER = "PROVIDER"
    INTEGRATION = "INTEGRATION"


SEARCH_SOURCES = frozenset(s.value for s in SearchSource)


class SearchTimeWindow(str, Enum):
    """Bounded time-window presets only (§4) — no free-form durations."""

    M15 = "15m"
    H1 = "1h"
    H6 = "6h"
    H24 = "24h"


class SearchErrorCode(str, Enum):
    """Error taxonomy (§14). Every error has NO side effect."""

    INVALID_QUERY = "INVALID_QUERY"
    SOURCE_NOT_ALLOWED = "SOURCE_NOT_ALLOWED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    REDACTION_FAILURE = "REDACTION_FAILURE"
    SEARCH_INTERNAL_ERROR = "SEARCH_INTERNAL_ERROR"


class SearchError(Exception):
    """One search failure with a taxonomy code (§14)."""

    def __init__(self, code: SearchErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code.value, "message": self.message}


@dataclass(frozen=True)
class SearchRequest:
    """Input contract (§4): bounded, normalized, literal-only.

    ``query`` is already normalized by the engine before any adapter
    sees it; adapters MUST treat it as a literal substring, never as
    regex/shell/path/SQL.
    """

    query: str
    source: SearchSource
    time_window: str = DEFAULT_TIME_WINDOW
    limit: int = DEFAULT_LIMIT


@dataclass(frozen=True)
class SearchResult:
    """Output projection (§8) — NO raw full log line / prompt / args.

    ``summary`` is a redacted, bounded (<=300 chars) human-readable
    projection. ``correlation_id`` carries only safe identifiers
    (request_id / run_id / event_id / job id) — never session tokens.
    """

    source: str
    timestamp: Optional[str]
    category: str
    summary: str
    severity: str
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "timestamp": self.timestamp,
            "category": self.category,
            "summary": self.summary,
            "severity": self.severity,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True)
class SearchOutcome:
    """Engine result: bounded results OR a taxonomy error. Never both."""

    source: SearchSource
    query: str
    time_window: str
    results: List[SearchResult] = field(default_factory=list)
    truncated: bool = False
    duration_ms: Optional[float] = None
    error: Optional[SearchError] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "source": self.source.value,
            "query": self.query,
            "time_window": self.time_window,
            "results": [r.to_dict() for r in self.results],
            "truncated": self.truncated,
            "duration_ms": self.duration_ms,
        }
        if self.error is not None:
            d["error"] = self.error.to_dict()
        return d


def window_start_utc(window: str, now: Optional[datetime] = None) -> datetime:
    """UTC datetime for a preset window start (fail closed on unknown)."""
    delta = TIME_WINDOW_PRESETS.get(window)
    if delta is None:
        raise SearchError(
            SearchErrorCode.INVALID_QUERY,
            f"unknown time_window preset: {window!r}",
        )
    now = now or datetime.now(timezone.utc)
    return now - delta
