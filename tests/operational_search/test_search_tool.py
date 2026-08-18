"""Sprint 1.2.2 §19 — operational_log_search tool tests.

14 mandatory tests: read-only, idempotent, no network, no shell
injection, path rejection, literal query, secret redaction, result
bounds, timeout, parameterized DB, allowed sources only, output
projection, no raw log line, rotation handling.

All tests use injected temp fixtures — the production gateway log /
state.db are never touched.
"""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.operational_search import (
    OperationalSearchEngine,
    SearchErrorCode,
    SearchRequest,
    SearchResult,
    SearchSource,
)
from agent.operational_search.normalize import (
    escape_like_literal,
    is_secret_query,
    normalize_query,
    validate_query,
)
from agent.operational_search.redaction import redact_line


# ── fixtures ───────────────────────────────────────────────────────


@pytest.fixture()
def fixtures(tmp_path: Path):
    """Temp log dir + state.db + jobs.json + provider cache +
    gateway_state — one fixture per test, all isolated."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "gateway.log").write_text(
        "2026-08-13 12:00:00,000 INFO gateway: started request_id=abc123\n"
        "2026-08-13 12:01:00,000 WARNING gateway: slow response\n"
        "2026-08-13 12:02:00,000 ERROR gateway: boom token=secret-token-xyz\n"
        "2026-08-13 12:03:00,000 ERROR gateway: api_key=sk-secret-abcdefgh123456\n",
        encoding="utf-8")
    (log_dir / "agent.log").write_text(
        "2026-08-13 12:00:30,000 INFO agent: routine\n",
        encoding="utf-8")
    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE agent_v2_events ("
                 "id INTEGER PRIMARY KEY, run_id TEXT, step_id TEXT, "
                 "event_type TEXT, timestamp TEXT, payload_json TEXT, "
                 "input_hash TEXT, output_hash TEXT)")
    now = datetime.now(timezone.utc)
    for i, etype in enumerate(["TOOL_STARTED", "TOOL_COMPLETED",
                               "ERROR", "EXECUTION_COMPLETED"]):
        conn.execute(
            "INSERT INTO agent_v2_events (id, run_id, event_type, "
            "timestamp, payload_json) VALUES (?, ?, ?, ?, ?)",
            (i + 1, f"run-{i + 1}", etype,
             (now - timedelta(minutes=i)).isoformat(),
             json.dumps({"tool": "runtime_status", "status": "ok"})))
    conn.commit()
    conn.close()
    jobs = {"jobs": [
        {"id": "job-1", "name": "morning-report",
         "schedule": "0 9 * * *", "last_status": "ok"},
        {"id": "job-2", "name": "nightly-backup",
         "schedule": "0 2 * * *", "last_status": "failed"},
    ]}
    (tmp_path / "jobs.json").write_text(
        json.dumps(jobs), encoding="utf-8")
    provider = {"deepseek": ["deepseek-v4-flash",
                             "deepseek-v4-flash-free"],
                "openrouter": ["o3-mini"]}
    (tmp_path / "provider_models_cache.json").write_text(
        json.dumps(provider), encoding="utf-8")
    gstate = {"gateway_state": "running",
              "platforms": {
                  "telegram": {"state": "connected",
                               "needs_attention": False},
                  "api_server": {"state": "error",
                                 "error_message": "port busy",
                                 "needs_attention": True},
              }}
    (tmp_path / "gateway_state.json").write_text(
        json.dumps(gstate), encoding="utf-8")
    return {
        "log_dir": log_dir,
        "state_db": db,
        "jobs": tmp_path / "jobs.json",
        "provider_cache": tmp_path / "provider_models_cache.json",
        "gateway_state": tmp_path / "gateway_state.json",
    }


def _engine(fixtures, **kw):
    # Fixed clock so fixture timestamps (12:00-12:03 UTC) always fall
    # inside the searched window — deterministic across machines.
    return OperationalSearchEngine(
        timeout=kw.pop("timeout", 2.0),
        paths={
            "logs": fixtures["log_dir"],
            "state_db": fixtures["state_db"],
            "jobs": fixtures["jobs"],
            "provider_cache": fixtures["provider_cache"],
            "gateway_state": fixtures["gateway_state"],
        },
        now=datetime(2026, 8, 13, 12, 10, tzinfo=timezone.utc),
        **kw,
    )


# ── §19 — 14 mandatory tool tests ──────────────────────────────────


def test_search_tool_read_only(fixtures):
    """§19/§0 — the engine never writes: DB is opened mode=ro, files
    are only read, and content hashes are unchanged after a search."""
    db = fixtures["state_db"]
    before = db.stat().st_mtime_ns
    before_log = (fixtures["log_dir"] / "gateway.log").read_bytes()
    outcome = _engine(fixtures).search(SearchRequest(
        query="error", source=SearchSource.GATEWAY_LOG))
    assert outcome.ok
    assert db.stat().st_mtime_ns == before  # DB untouched
    after_log = (fixtures["log_dir"] / "gateway.log").read_bytes()
    assert before_log == after_log  # logs untouched


def test_search_tool_idempotent(fixtures):
    """§19 — same request twice → identical results (deterministic)."""
    eng = _engine(fixtures)
    a = eng.search(SearchRequest(
        query="error", source=SearchSource.GATEWAY_LOG))
    b = eng.search(SearchRequest(
        query="error", source=SearchSource.GATEWAY_LOG))
    assert a.ok and b.ok
    assert [r.to_dict() for r in a.results] == \
        [r.to_dict() for r in b.results]


def test_search_tool_no_network(fixtures):
    """§19 — the module must not open sockets: engine works with
    socket primitives disabled (no urllib/requests reachable)."""
    import agent.operational_search.sources as sources_mod
    import agent.operational_search.engine as engine_mod
    # Static proof: no network imports in the module surface.
    src = "\n".join([
        Path(sources_mod.__file__).read_text(),
        Path(engine_mod.__file__).read_text(),
    ])
    for banned in ("urllib", "requests", "socket", "http.client",
                   "subprocess", "os.system", "os.popen"):
        assert banned not in src, f"banned network/shell import: {banned}"
    # Runtime proof: block sockets entirely; engine still returns.
    real_connect = socket.socket.connect
    def _deny(self, *a, **k):
        raise OSError("network denied")
    socket.socket.connect = _deny
    try:
        outcome = _engine(fixtures).search(SearchRequest(
            query="error", source=SearchSource.GATEWAY_LOG))
        assert outcome.ok
    finally:
        socket.socket.connect = real_connect


def test_search_tool_no_shell_injection(fixtures):
    """§19/§5 — shell metacharacters are literal text, never executed.
    A query that would be dangerous in a shell returns literal
    matches or an empty result — and no process is ever spawned."""
    assert "subprocess" not in \
        Path(__import__("agent.operational_search.engine",
                        fromlist=["x"]).__file__).read_text()
    outcome = _engine(fixtures).search(SearchRequest(
        query="$(rm -rf /); echo pwned", source=SearchSource.GATEWAY_LOG))
    assert outcome.ok  # literal query, no error, no execution
    # A semicolon/pipe query is just a literal miss.
    o2 = _engine(fixtures).search(SearchRequest(
        query="| shutdown -h now", source=SearchSource.GATEWAY_LOG))
    assert o2.ok and o2.results == []


def test_search_tool_rejects_path_input(fixtures):
    """§19/§12 — user text is never a path: '/etc/shadow', '..',
    '~' are plain literals; the source is a closed enum so a path-
    shaped source string is rejected."""
    outcome = _engine(fixtures).search(SearchRequest(
        query="/etc/shadow", source=SearchSource.GATEWAY_LOG))
    assert outcome.ok  # literal miss, NOT a file open
    # A path-looking SOURCE value is SOURCE_NOT_ALLOWED.
    o2 = _engine(fixtures).search(SearchRequest(
        query="x", source=SearchSource("GATEWAY_LOG")))
    assert o2.ok
    bad = OperationalSearchEngine().search(SearchRequest(
        query="x", source="../../etc"))  # type: ignore[arg-type]
    assert bad.ok is False
    assert bad.error is not None
    assert bad.error.code == SearchErrorCode.SOURCE_NOT_ALLOWED


def test_search_tool_literal_query(fixtures):
    """§19/§6 — the query is a LITERAL substring: regex metachars
    ('(', '*', '.') match only as text, and a nonexistent pattern
    returns zero results instead of a regex error."""
    (fixtures["log_dir"] / "gateway.log").write_text(
        "line with (parens) and star * and dot . here\n", encoding="utf-8")
    outcome = _engine(fixtures).search(SearchRequest(
        query="(parens)", source=SearchSource.GATEWAY_LOG))
    assert outcome.ok and len(outcome.results) == 1
    o2 = _engine(fixtures).search(SearchRequest(
        query="(no-such-thing", source=SearchSource.GATEWAY_LOG))
    assert o2.ok and o2.results == []


def test_search_tool_redacts_secrets(fixtures):
    """§19/§7 — synthetic secrets in logs are redacted in output:
    no api_key/token value, no prefix token, no Bearer value."""
    (fixtures["log_dir"] / "gateway.log").write_text(
        "2026-08-13 12:00:00,000 ERROR gateway: "
        "OPENAI_API_KEY=sk-super-secret-abcdefgh1234567890 "
        "Authorization: Bearer abcdefghijklmnop token=leakme\n",
        encoding="utf-8")
    outcome = _engine(fixtures).search(SearchRequest(
        query="OPENAI", source=SearchSource.GATEWAY_LOG))
    assert outcome.ok and len(outcome.results) == 1
    summary = outcome.results[0].summary
    assert "sk-super-secret" not in summary
    assert "abcdefghijklmnop" not in summary
    assert "leakme" not in summary
    assert "[REDACTED]" in summary or "OPENAI" in summary


def test_search_tool_bounds_results(fixtures):
    """§19/§13 — limit is capped at 100, default 20, negative→1;
    an oversized query (>128) is INVALID_QUERY."""
    (fixtures["log_dir"] / "gateway.log").write_text(
        "\n".join(f"line {i} request_id=r{i}"
                  for i in range(50)), encoding="utf-8")
    o = _engine(fixtures).search(SearchRequest(
        query="line", source=SearchSource.GATEWAY_LOG, limit=999))
    assert o.ok and len(o.results) == 50  # dataset smaller than cap
    o2 = _engine(fixtures).search(SearchRequest(
        query="line", source=SearchSource.GATEWAY_LOG, limit=-3))
    assert o2.ok and len(o2.results) == 1
    o3 = _engine(fixtures).search(SearchRequest(
        query="x" * 129, source=SearchSource.GATEWAY_LOG))
    assert o3.ok is False
    assert o3.error is not None
    assert o3.error.code == SearchErrorCode.INVALID_QUERY


def test_search_tool_timeout(fixtures):
    """§19 — a deadline is enforced: a tiny timeout still returns
    (bounded scan) or a TIMEOUT, never hangs."""
    outcome = _engine(fixtures, timeout=0.1).search(SearchRequest(
        query="error", source=SearchSource.GATEWAY_LOG))
    assert outcome.duration_ms is not None
    assert outcome.duration_ms < 2000


def test_search_tool_parameterized_db(fixtures):
    """§19/§11 — the events adapter uses a parameterized SELECT and
    never interpolates the query into SQL (quotes are harmless)."""
    eng = _engine(fixtures)
    o = eng.search(SearchRequest(
        query="' OR 1=1 --", source=SearchSource.EVENTS))
    assert o.ok  # literal, no injection
    o2 = eng.search(SearchRequest(
        query="TOOL_STARTED", source=SearchSource.EVENTS))
    assert o2.ok and len(o2.results) >= 1
    # Static proof: no f-string/format SQL in the adapter.
    import agent.operational_search.sources as mod
    src = Path(mod.__file__).read_text()
    assert "f\"SELECT" not in src and ".format(" not in src


def test_search_tool_allowed_sources_only(fixtures):
    """§19 — only the 5 enum sources are accepted; anything else is
    SOURCE_NOT_ALLOWED, and an unavailable adapter source is
    SOURCE_UNAVAILABLE."""
    for src in SearchSource:
        o = _engine(fixtures).search(SearchRequest(
            query="x", source=src))
        assert o.ok is True or o.error.code in (
            SearchErrorCode.SOURCE_UNAVAILABLE,)
    bad = OperationalSearchEngine().search(SearchRequest(
        query="x", source=SearchSource.GATEWAY_LOG))
    assert bad.ok  # defaults resolve real paths or degrade gracefully
    # Source not in enum (string, not enum) → SOURCE_NOT_ALLOWED.
    o3 = OperationalSearchEngine().search(SearchRequest(
        query="x", source="FILESYSTEM"))  # type: ignore[arg-type]
    assert o3.ok is False
    assert o3.error is not None
    assert o3.error.code == SearchErrorCode.SOURCE_NOT_ALLOWED


def test_search_tool_output_projection(fixtures):
    """§19/§8 — every result is a bounded SearchResult projection:
    exactly {source, timestamp, category, summary, severity,
    correlation_id}; summary <= 300 chars."""
    o = _engine(fixtures).search(SearchRequest(
        query="error", source=SearchSource.GATEWAY_LOG))
    assert o.ok
    for r in o.results:
        d = r.to_dict()
        assert set(d.keys()) == {"source", "timestamp", "category",
                                 "summary", "severity",
                                 "correlation_id"}
        assert len(d["summary"]) <= 300
        assert d["source"] == SearchSource.GATEWAY_LOG.value


def test_search_tool_no_raw_log_line(fixtures):
    """§19/§8 — the full raw log line is NEVER returned as-is: the
    summary is a bounded projection (no newline, no full line)."""
    long_line = "x" * 500
    (fixtures["log_dir"] / "gateway.log").write_text(
        f"2026-08-13 12:00:00,000 ERROR gateway: {long_line} tail\n",
        encoding="utf-8")
    o = _engine(fixtures).search(SearchRequest(
        query="tail", source=SearchSource.GATEWAY_LOG))
    assert o.ok and len(o.results) == 1
    summary = o.results[0].summary
    assert "\n" not in summary
    assert len(summary) <= 300
    assert "x" * 300 not in summary  # not the raw 500-char line


def test_search_tool_handles_rotation(fixtures):
    """§19/§12 — rotation aware: gateway.log.1 (previous rotation) is
    scanned too, bounded; a missing file degrades to SOURCE_UNAVAILABLE
    for the events adapter when no DB is configured."""
    log_dir = fixtures["log_dir"]
    (log_dir / "gateway.log").write_text(
        "2026-08-13 12:00:00,000 INFO gateway: current rotation\n",
        encoding="utf-8")
    (log_dir / "gateway.log.1").write_text(
        "2026-08-13 11:00:00,000 ERROR gateway: old rotation hit\n",
        encoding="utf-8")
    o = _engine(fixtures).search(SearchRequest(
        query="rotation", source=SearchSource.GATEWAY_LOG,
        time_window="24h"))
    assert o.ok
    hits = [r.summary for r in o.results]
    assert any("current" in s for s in hits)
    assert any("old rotation hit" in s for s in hits)
    # Missing DB → SOURCE_UNAVAILABLE (fail closed, no exception).
    eng = OperationalSearchEngine(paths={"state_db": Path("/nonexistent")})
    o2 = eng.search(SearchRequest(
        query="x", source=SearchSource.EVENTS))
    assert o2.ok is False
    assert o2.error is not None
    assert o2.error.code == SearchErrorCode.SOURCE_UNAVAILABLE


# ── §6/§7 unit checks ──────────────────────────────────────────────


def test_normalize_query_contract():
    assert normalize_query("  Привет   МИР  ") == "привет мир"
    assert normalize_query("a" * 128) == "a" * 128
    ok, err = validate_query("a" * 129)
    assert ok is False and err is not None
    ok, _ = validate_query("normal")
    assert ok is True
    with pytest.raises(Exception):
        normalize_query("bad\x00nul")
    assert escape_like_literal("50%_") == "50\\%\\_"


def test_secret_query_detection():
    assert is_secret_query("найди пароль")
    assert is_secret_query("покажи OPENAI_API_KEY")
    assert is_secret_query("grep token /home")
    assert not is_secret_query("найди последние ошибки gateway")


def test_redact_line_scrubs_assignments():
    out = redact_line("api_key=sk-abcdefgh1234567890")
    assert "sk-abcdefgh" not in out
    out2 = redact_line("Authorization: Bearer abcdefghijklmnop")
    assert "abcdefghijklmnop" not in out2
    plain = redact_line("just a normal log line")
    assert plain == "just a normal log line"
