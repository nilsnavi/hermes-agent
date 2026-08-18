"""Operational Search — verified READ_ONLY local search (Sprint 1.2.2).

```
  request text
      |
      v
  OperationalSearchEngine.search(SearchRequest)
      |  (pure Python, no LLM, no network, no shell, no writes)
      v
  adapter[source] -> bounded scan (allowlist paths / parameterized
                    read-only SQL / metadata JSON) -> project
                    -> redact (existing redaction layer) -> results
```

Contract (Sprint 1.2.2 §0-§14):

- READ_ONLY by construction: file scans read bounded byte windows,
  DB reads are ``mode=ro`` parameterized SELECTs, JSON sources are
  parsed read-only. Nothing in this package writes, mutates PRAGMAs,
  or executes shell commands.
- No subprocess, no network: pure stdlib file/JSON/SQLite scanning.
- Query is a LITERAL substring/token search after normalization
  (unicode NFC, casefold, trim, collapse whitespace); user input is
  never interpreted as regex, glob, shell syntax, path, or SQL.
- Every output line passes the existing redaction layer before it
  can leave the engine; sensitive candidates are redacted, never
  skipped "for later".
- Bounded: query <=128 chars, limit <=100, per-file byte cap,
  hard timeout <=2s, one source per request.
- Deterministic: same request -> same ordered result set (scan
  order is fixed; ties break by id/timestamp ascending).

Sources (each implemented by a separate adapter, §10):

    GATEWAY_LOG   allowlisted gateway/agent/errors log files
    EVENTS        agent_v2_events timeline (read-only SQL)
    SCHEDULER     cron jobs.json metadata
    PROVIDER      provider_models_cache.json metadata
    INTEGRATION   gateway_state.json platform health

The package is standalone (stdlib-only imports at module level;
``agent.redact`` is imported lazily inside the redaction function so
this module never bricks when imported outside the repo).
"""

from .engine import OperationalSearchEngine, SearchOutcome
from .models import (
    SEARCH_SOURCES,
    SearchError,
    SearchErrorCode,
    SearchRequest,
    SearchResult,
    SearchSource,
    SearchTimeWindow,
)

__all__ = [
    "OperationalSearchEngine",
    "SearchOutcome",
    "SearchRequest",
    "SearchResult",
    "SearchSource",
    "SearchTimeWindow",
    "SearchError",
    "SearchErrorCode",
    "SEARCH_SOURCES",
]
