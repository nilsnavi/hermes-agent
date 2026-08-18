"""Source adapters (§10) — one adapter per allowed source.

Each adapter owns the storage details of ONE source and returns
already-projected :class:`SearchResult` items. The engine facade
never knows a source's storage; adapters never know the router.

Shared safety rules (all adapters):

- User input is a NORMALIZED LITERAL substring only.
- File adapters read ONLY from an explicit allowlist path (no user
  path ever), bounded byte window, rotation aware, fail closed.
- The events adapter uses ``mode=ro`` parameterized SELECT only.
- Every projection passes :func:`redact_line` before returning.
- The deadline (monotonic seconds) is checked between chunks; an
  adapter past its deadline stops scanning and returns what it has
  (the engine turns a deadline miss into TIMEOUT when nothing was
  produced in time).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import (
    MAX_BYTES_PER_FILE,
    MAX_SCAN_LINES,
    MAX_SUMMARY_LENGTH,
    SearchError,
    SearchErrorCode,
    SearchRequest,
    SearchResult,
    SearchSource,
    window_start_utc,
)
from .normalize import escape_like_literal
from .redaction import redact_line

#: Level word -> severity mapping (gateway log projection).
_LEVEL_SEVERITY = {
    "ERROR": "error",
    "CRITICAL": "error",
    "WARNING": "warning",
    "WARN": "warning",
    "INFO": "info",
    "DEBUG": "info",
}

#: Logger categories that classify a line as integration/platform
#: related (INTEGRATION adapter interest).
_INTEGRATION_LOGGERS = (
    "telegram", "mcp", "matrix", "discord", "slack", "whatsapp",
    "platform", "hermes_plugins.max", "feishu", "api_server",
)

#: Timestamp prefixes seen in gateway logs (rotating logger).
_LOG_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")
_REQUEST_ID_RE = re.compile(r"\brequest_id=([A-Za-z0-9_-]+)")
_RUN_ID_RE = re.compile(r"\brun_id=([A-Za-z0-9_-]+)")
_EVENT_ID_RE = re.compile(r"\bevent_id=([A-Za-z0-9_-]+)")
_JOB_ID_RE = re.compile(r"\bjob_id=([A-Za-z0-9_-]+)")


def _bounded_summary(text: str) -> str:
    """Collapse whitespace + hard cap to MAX_SUMMARY_LENGTH chars."""
    t = " ".join(text.split())
    return t[:MAX_SUMMARY_LENGTH]


def _correlation_id(line: str) -> Optional[str]:
    """Safe identifiers only (§9) — request/run/event/job id, in that
    order; NEVER session tokens."""
    for rx in (_REQUEST_ID_RE, _RUN_ID_RE, _EVENT_ID_RE, _JOB_ID_RE):
        m = rx.search(line)
        if m:
            return m.group(1)
    return None


class SearchAdapter:
    """Base: one source, one allowlist config, literal search."""

    source: SearchSource = SearchSource.GATEWAY_LOG

    def __init__(self, paths: Dict[str, Path],
                 now: Optional[datetime] = None) -> None:
        #: Storage location overrides (tests inject temp dirs); the
        #: adapter resolves ONLY the paths this source is allowed to
        #: touch and ignores everything else.
        self._paths = dict(paths or {})
        self._now = now or datetime.now(timezone.utc)

    # ── helpers ────────────────────────────────────────────────────

    def _path(self, key: str) -> Optional[Path]:
        p = self._paths.get(key)
        if p is None:
            return None
        path = Path(p)
        return path if path.exists() else None

    def _deadline_ok(self, deadline: float) -> bool:
        import time
        return time.monotonic() < deadline

    def _emit(self, *, timestamp: Optional[str], category: str,
              summary: str, severity: str,
              correlation_id: Optional[str]) -> SearchResult:
        return SearchResult(
            source=self.source.value,
            timestamp=timestamp,
            category=category,
            summary=redact_line(_bounded_summary(summary)),
            severity=severity,
            correlation_id=correlation_id,
        )

    def search(self, request: SearchRequest,
               deadline: float) -> List[SearchResult]:
        raise NotImplementedError


class GatewayLogAdapter(SearchAdapter):
    """GATEWAY_LOG — allowlisted log files, tail-bounded, rotated.

    Reads ONLY ``gateway.log`` / ``agent.log`` / ``errors.log`` under
    the configured log dir (plus the ``.1`` rotated sibling). Scans a
    bounded byte window from the END of each file (most recent
    first), filters by time window when a parseable timestamp is
    present, and projects a redacted summary — never the raw line.
    """

    source = SearchSource.GATEWAY_LOG

    def __init__(self, paths: Dict[str, Path],
                 now: Optional[datetime] = None) -> None:
        super().__init__(paths, now)
        #: Allowlist of basenames this adapter may open. Fail closed:
        #: a name not in this set is never opened, whatever the path
        #: config says.
        self._allowlist = {"gateway.log", "agent.log", "errors.log"}

    def search(self, request: SearchRequest,
               deadline: float) -> List[SearchResult]:
        log_dir = self._path("logs") or Path(
            os.path.expanduser("~/.hermes/logs"))
        results: List[SearchResult] = []
        window_start = window_start_utc(request.time_window, self._now)
        for name in sorted(self._allowlist):
            if not self._deadline_ok(deadline):
                break
            if len(results) >= request.limit:
                break
            base = log_dir / name
            if not base.exists():
                continue
            # Rotation aware: newest file first, then the .1 sibling.
            for candidate in (base, Path(str(base) + ".1")):
                if not candidate.exists() or \
                        not self._deadline_ok(deadline):
                    continue
                results.extend(
                    self._scan_file(candidate, request, window_start,
                                    deadline, results))
                if len(results) >= request.limit:
                    break
        return results[: request.limit]

    def _scan_file(self, path: Path, request: SearchRequest,
                   window_start: datetime, deadline: float,
                   collected: List[SearchResult]) -> List[SearchResult]:
        out: List[SearchResult] = []
        try:
            size = path.stat().st_size
            if size <= 0:
                return out
            read_bytes = min(size, MAX_BYTES_PER_FILE)
            with open(path, "rb") as fh:
                fh.seek(size - read_bytes)
                if read_bytes < size:  # skip partial first line
                    fh.readline()
                tail = fh.read().decode("utf-8", "replace")
        except OSError:
            return out  # file vanished mid-scan: skip, no side effect
        query = request.query.casefold()
        for raw in tail.splitlines()[-MAX_SCAN_LINES:]:
            if not self._deadline_ok(deadline) or \
                    len(collected) + len(out) >= request.limit:
                break
            line = raw.strip()
            if not line or query not in line.casefold():
                continue
            ts = None
            m = _LOG_TS_RE.match(line)
            if m:
                try:
                    ts = datetime.fromisoformat(
                        m.group(1).replace(" ", "T")).replace(
                            tzinfo=timezone.utc)
                except ValueError:
                    ts = None
                if ts is not None and ts < window_start:
                    continue
            level_m = re.search(r"\b(ERROR|WARNING|WARN|INFO|DEBUG|"
                                r"CRITICAL)\b", line)
            severity = _LEVEL_SEVERITY.get(
                level_m.group(1) if level_m else "", "info")
            category = line.split(" ", 2)[2].split(":")[0] \
                if len(line.split(" ", 2)) > 2 else "gateway"
            out.append(self._emit(
                timestamp=m.group(1) if m else None,
                category=category,
                summary=line,
                severity=severity,
                correlation_id=_correlation_id(line),
            ))
        return out


class EventsAdapter(SearchAdapter):
    """EVENTS — agent_v2_events timeline, read-only parameterized SQL.

    Opens ``state.db`` with ``mode=ro`` (impossible to write), uses a
    fixed parameterized SELECT (no dynamic SQL), a bounded LIMIT and
    a literal LIKE with escaped user input. Projection is the event
    type + a redacted payload excerpt, never the raw payload.
    """

    source = SearchSource.EVENTS

    def __init__(self, paths: Dict[str, Path],
                 now: Optional[datetime] = None) -> None:
        super().__init__(paths, now)
        self._db_path = None
        if "state_db" in self._paths:
            # Explicitly configured path: fail closed when missing
            # (§12) — never silently fall back to the default.
            p = Path(self._paths["state_db"])
            self._db_path = p if p.exists() else None
        else:
            home_db = Path(
                os.path.expanduser("~/.hermes/state.db"))
            if home_db.exists():
                self._db_path = home_db

    def search(self, request: SearchRequest,
               deadline: float) -> List[SearchResult]:
        if self._db_path is None:
            raise SearchError(
                SearchErrorCode.SOURCE_UNAVAILABLE,
                "events database not found")
        window_start = window_start_utc(request.time_window, self._now)
        like = f"%{escape_like_literal(request.query)}%"
        uri = f"file:{self._db_path}?mode=ro"
        results: List[SearchResult] = []
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=1.0)
            try:
                cur = conn.execute(
                    "SELECT id, run_id, event_type, timestamp, "
                    "payload_json FROM agent_v2_events "
                    "WHERE timestamp >= ? "
                    "AND (event_type LIKE ? ESCAPE '\\' "
                    "OR payload_json LIKE ? ESCAPE '\\') "
                    "ORDER BY id DESC LIMIT ?",
                    (window_start.isoformat(), like, like,
                     request.limit * 4),
                )
                for row in cur:
                    if not self._deadline_ok(deadline):
                        break
                    event_id, run_id, etype, ts, payload = row
                    ts_str = str(ts) if ts is not None else None
                    summary = etype or "event"
                    if payload:
                        try:
                            data = json.loads(payload)
                            if isinstance(data, dict):
                                parts = []
                                for k in ("tool", "tool_name",
                                          "stop_reason", "status"):
                                    v = data.get(k)
                                    if isinstance(v, str) and v:
                                        parts.append(f"{k}={v}")
                                if parts:
                                    summary = f"{etype} " + \
                                        " ".join(parts)
                        except (ValueError, TypeError):
                            pass
                    results.append(self._emit(
                        timestamp=ts_str,
                        category=etype or "event",
                        summary=summary,
                        severity=_event_severity(etype),
                        correlation_id=run_id or f"event-{event_id}",
                    ))
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise SearchError(
                SearchErrorCode.SOURCE_UNAVAILABLE,
                f"events database unreadable: {exc}") from exc
        return results[: request.limit]


def _event_severity(event_type: Optional[str]) -> str:
    et = (event_type or "").upper()
    if "ERROR" in et or "FAIL" in et or "DENIED" in et:
        return "error"
    if "WARN" in et or "TIMEOUT" in et:
        return "warning"
    return "info"


class SchedulerAdapter(SearchAdapter):
    """SCHEDULER — jobs.json read-only metadata.

    Loads the persisted scheduler state (job id/name/schedule/status)
    and literal-matches the query against the projected metadata.
    Never touches the scheduler itself — read-only file parse.
    """

    source = SearchSource.SCHEDULER

    def search(self, request: SearchRequest,
               deadline: float) -> List[SearchResult]:
        jobs_path = self._path("jobs") or Path(
            os.path.expanduser("~/.hermes/cron/jobs.json"))
        if not jobs_path.exists():
            raise SearchError(
                SearchErrorCode.SOURCE_UNAVAILABLE,
                "scheduler metadata not found")
        try:
            with open(jobs_path, "r", encoding="utf-8") as fh:
                raw = fh.read(MAX_BYTES_PER_FILE)
            data = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise SearchError(
                SearchErrorCode.SOURCE_UNAVAILABLE,
                f"scheduler metadata unreadable: {exc}") from exc
        jobs = data if isinstance(data, list) else \
            data.get("jobs", []) if isinstance(data, dict) else []
        query = request.query.casefold()
        results: List[SearchResult] = []
        for job in jobs:
            if not self._deadline_ok(deadline) or \
                    len(results) >= request.limit:
                break
            if not isinstance(job, dict):
                continue
            jid = str(job.get("id", ""))
            name = str(job.get("name", ""))
            schedule = str(job.get("schedule", ""))
            status = str(job.get("last_status", ""))
            blob = " ".join((jid, name, schedule, status)).casefold()
            if query not in blob:
                continue
            severity = "error" if status in ("failed", "error") else \
                ("warning" if status == "timeout" else "info")
            summary = f"job {name or jid}"
            if schedule:
                summary += f" schedule={schedule}"
            if status:
                summary += f" status={status}"
            results.append(self._emit(
                timestamp=str(job.get("last_run_at")
                              or job.get("next_run_at") or ""),
                category="scheduler",
                summary=summary,
                severity=severity,
                correlation_id=jid or None,
            ))
        return results


class ProviderAdapter(SearchAdapter):
    """PROVIDER — provider health/error metadata (read-only).

    Reads the persisted provider models cache (provider ids + model
    names) and literal-matches the query. Health/error signals come
    from the cache's error fields when present. No provider probing,
    no credential access.
    """

    source = SearchSource.PROVIDER

    def search(self, request: SearchRequest,
               deadline: float) -> List[SearchResult]:
        cache_path = self._path("provider_cache") or Path(
            os.path.expanduser("~/.hermes/provider_models_cache.json"))
        if not cache_path.exists():
            raise SearchError(
                SearchErrorCode.SOURCE_UNAVAILABLE,
                "provider metadata not found")
        try:
            with open(cache_path, "r", encoding="utf-8") as fh:
                data = json.loads(fh.read(MAX_BYTES_PER_FILE))
        except (OSError, ValueError) as exc:
            raise SearchError(
                SearchErrorCode.SOURCE_UNAVAILABLE,
                f"provider metadata unreadable: {exc}") from exc
        if not isinstance(data, dict):
            return []
        query = request.query.casefold()
        results: List[SearchResult] = []
        for provider, value in data.items():
            if not self._deadline_ok(deadline) or \
                    len(results) >= request.limit:
                break
            pid = str(provider).casefold()
            models = value if isinstance(value, (list, dict)) else []
            model_names = []
            if isinstance(models, list):
                model_names = [str(m) for m in models if m]
            elif isinstance(models, dict):
                model_names = [str(k) for k in models.keys() if k]
            blob = " ".join([pid] + [m.casefold()
                                     for m in model_names])
            if query not in blob:
                continue
            summary = f"provider {provider}"
            if model_names:
                summary += f" models={len(model_names)}"
            results.append(self._emit(
                timestamp=None,
                category=str(provider),
                summary=summary,
                severity="info",
                correlation_id=None,
            ))
        return results


class IntegrationAdapter(SearchAdapter):
    """INTEGRATION — platform health/reconnect/error summaries.

    Reads the persisted gateway state (platforms section) and matches
    the query against platform names + states. Reconnect/error
    signals surface as severity. Read-only file parse.
    """

    source = SearchSource.INTEGRATION

    def search(self, request: SearchRequest,
               deadline: float) -> List[SearchResult]:
        state_path = self._path("gateway_state") or Path(
            os.path.expanduser("~/.hermes/gateway_state.json"))
        if not state_path.exists():
            raise SearchError(
                SearchErrorCode.SOURCE_UNAVAILABLE,
                "integration state not found")
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                data = json.loads(fh.read(MAX_BYTES_PER_FILE))
        except (OSError, ValueError) as exc:
            raise SearchError(
                SearchErrorCode.SOURCE_UNAVAILABLE,
                f"integration state unreadable: {exc}") from exc
        platforms = data.get("platforms", {}) \
            if isinstance(data, dict) else {}
        if not isinstance(platforms, dict):
            return []
        query = request.query.casefold()
        results: List[SearchResult] = []
        for name, info in platforms.items():
            if not self._deadline_ok(deadline) or \
                    len(results) >= request.limit:
                break
            if not isinstance(info, dict):
                continue
            state = str(info.get("state", "unknown"))
            err = info.get("error_message")
            blob = " ".join((str(name), state,
                             str(err or ""))).casefold()
            if query not in blob:
                continue
            severity = "error" if state == "error" or err else \
                ("warning" if info.get("needs_attention") else "info")
            summary = f"integration {name} state={state}"
            if err:
                summary += f" error={err}"
            results.append(self._emit(
                timestamp=str(info.get("updated_at") or ""),
                category=str(name),
                summary=summary,
                severity=severity,
                correlation_id=None,
            ))
        return results


ADAPTERS: Dict[SearchSource, type] = {
    SearchSource.GATEWAY_LOG: GatewayLogAdapter,
    SearchSource.EVENTS: EventsAdapter,
    SearchSource.SCHEDULER: SchedulerAdapter,
    SearchSource.PROVIDER: ProviderAdapter,
    SearchSource.INTEGRATION: IntegrationAdapter,
}
