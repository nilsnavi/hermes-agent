"""Operational Search engine facade (Sprint 1.2.2 §10).

The facade owns the input contract and the deadline; adapters own
storage details. The engine NEVER knows where a source's data lives
and NEVER passes user input anywhere but into a literal adapter
match.

Error handling: any taxonomy failure returns a ``SearchOutcome``
with ``error`` set — only a genuine internal fault (adapter
explosion) is converted to SEARCH_INTERNAL_ERROR and still returned
as an outcome, never raised. No side effects on any path.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .models import (
    DEFAULT_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TIME_WINDOW,
    MAX_LIMIT,
    SEARCH_SOURCES,
    SearchError,
    SearchErrorCode,
    SearchOutcome,
    SearchRequest,
    SearchSource,
)
from .normalize import normalize_query
from .sources import ADAPTERS


class OperationalSearchEngine:
    """Verified READ_ONLY local operational search (§0-§14).

    Parameters mirror the tool metadata contract (§3):

    - ``timeout`` — hard cap <= 2s per request (default 2.0).
    - ``paths`` — storage overrides for tests; when empty, adapters
      resolve their allowlisted default locations.
    - ``now`` — injectable clock for deterministic window tests.

    Usage::

        engine = OperationalSearchEngine()
        outcome = engine.search(SearchRequest(
            query="telegram", source=SearchSource.INTEGRATION))
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        paths: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> None:
        self._timeout = max(0.1, min(float(timeout),
                                     DEFAULT_TIMEOUT_SECONDS))
        self._paths = dict(paths or {})
        self._now = now or datetime.now(timezone.utc)

    # ── public ─────────────────────────────────────────────────────

    def search(self, request: SearchRequest) -> SearchOutcome:
        started = time.monotonic()
        try:
            return self._search_checked(request, started)
        except SearchError as exc:
            return SearchOutcome(
                source=request.source,
                query=request.query,
                time_window=request.time_window,
                error=exc,
                duration_ms=self._elapsed(started),
            )
        except Exception as exc:  # adapter internal fault — fail closed
            return SearchOutcome(
                source=request.source,
                query=request.query,
                time_window=request.time_window,
                error=SearchError(
                    SearchErrorCode.SEARCH_INTERNAL_ERROR,
                    f"search failed internally: {type(exc).__name__}"),
                duration_ms=self._elapsed(started),
            )

    def _elapsed(self, started: float) -> float:
        return round((time.monotonic() - started) * 1000.0, 3)

    # ── internals ──────────────────────────────────────────────────

    def _search_checked(self, request: SearchRequest,
                        started: float) -> SearchOutcome:
        # Input contract (§4): normalize FIRST — the query that
        # reaches adapters is validated literal text.
        query = normalize_query(request.query)
        # Source must be a closed-enum member, never user text.
        if not isinstance(request.source, SearchSource) or \
                request.source.value not in SEARCH_SOURCES:
            raise SearchError(
                SearchErrorCode.SOURCE_NOT_ALLOWED,
                "source not allowed")
        window = request.time_window or DEFAULT_TIME_WINDOW
        limit = request.limit or DEFAULT_LIMIT
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise SearchError(
                SearchErrorCode.INVALID_QUERY,
                "limit must be an integer")
        limit = max(1, min(limit, MAX_LIMIT))
        deadline = started + self._timeout
        adapter_type = ADAPTERS.get(request.source)
        if adapter_type is None:
            raise SearchError(
                SearchErrorCode.SOURCE_NOT_ALLOWED,
                "source not allowed")
        adapter = adapter_type(self._paths, now=self._now)
        results = adapter.search(
            SearchRequest(query=query, source=request.source,
                          time_window=window, limit=limit),
            deadline,
        )
        truncated = len(results) > limit
        return SearchOutcome(
            source=request.source,
            query=query,
            time_window=window,
            results=results[:limit],
            truncated=truncated,
            duration_ms=self._elapsed(started),
        )
