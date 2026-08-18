"""Sprint 1.2.2 §24/§25 — search tool benchmark + security fixtures.

Usage:
    venv/bin/python tests/operational_search/benchmark_search.py

Benchmarks 1000 safe searches per adapter over a bounded synthetic
dataset and reports p50/p95/max per adapter + router decision p95.
All fixtures are synthetic; real credentials are NEVER used (§25).
"""

import json
import statistics
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import RouterMode
from agent.intent_router.router import IntentRouter
from agent.operational_search import (
    OperationalSearchEngine,
    SearchRequest,
    SearchSource,
)

#: Synthetic secret-laden lines (§25) — fake credentials only.
_SECRET_LINES = [
    "2026-08-13 12:00:00,000 ERROR gateway: api_key=sk-fake-openai-abcdefghijklmnop123456",
    "2026-08-13 12:00:01,000 WARNING gateway: Authorization: Bearer fakebearer-token-abcdef",
    "2026-08-13 12:00:02,000 ERROR gateway: password=Sup3rFake!Passw0rd cookie=session-fake-abc",
    "2026-08-13 12:00:03,000 INFO gateway: OPENAI_API_KEY=sk-fake-key-9876543210 request_id=bench-1",
    "2026-08-13 12:00:04,000 ERROR gateway: provider credential client_secret=fake-client-secret-xyz",
]


def _build_dataset(tmp: Path) -> dict:
    logs = tmp / "logs"
    logs.mkdir()
    lines = list(_SECRET_LINES)
    for i in range(1200):
        lines.append(
            f"2026-08-13 {12 + (i % 10):02d}:{(i % 60):02d}:{(i % 60):02d}"
            f",000 INFO gateway: routine line {i} "
            f"request_id=bench-{i} category=job{i % 7}")
    (logs / "gateway.log").write_text("\n".join(lines), encoding="utf-8")

    db = tmp / "state.db"
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE agent_v2_events ("
                 "id INTEGER PRIMARY KEY, run_id TEXT, step_id TEXT, "
                 "event_type TEXT, timestamp TEXT, payload_json TEXT, "
                 "input_hash TEXT, output_hash TEXT)")
    now = datetime.now(timezone.utc)
    for i in range(1200):
        conn.execute(
            "INSERT INTO agent_v2_events (id, run_id, event_type, "
            "timestamp, payload_json) VALUES (?, ?, ?, ?, ?)",
            (i + 1, f"run-bench-{i}", "TOOL_STARTED" if i % 2 else
             "TOOL_COMPLETED",
             (now - timedelta(minutes=i % 240)).isoformat(),
             json.dumps({"tool": "runtime_status", "status": "ok"})))
    conn.commit()
    conn.close()

    jobs = {"jobs": [
        {"id": f"job-{i}", "name": f"report-{i % 13}",
         "schedule": "0 9 * * *", "last_status": "ok" if i % 5 else
         "failed"} for i in range(300)]}
    (tmp / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    provider = {f"provider-{i}": [f"model-{i}-a", f"model-{i}-b"]
                for i in range(60)}
    (tmp / "provider_models_cache.json").write_text(
        json.dumps(provider), encoding="utf-8")
    gstate = {"gateway_state": "running", "platforms": {
        f"platform-{i}": {"state": "connected", "needs_attention": False}
        for i in range(30)}}
    (tmp / "gateway_state.json").write_text(
        json.dumps(gstate), encoding="utf-8")
    return {"logs": logs, "state_db": db, "jobs": tmp / "jobs.json",
            "provider_cache": tmp / "provider_models_cache.json",
            "gateway_state": tmp / "gateway_state.json"}


def _percentile(data, p):
    s = sorted(data)
    k = max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def _bench(fn, n=1000):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    return {"p50": round(_percentile(times, 50), 3),
            "p95": round(_percentile(times, 95), 3),
            "max": round(max(times), 3),
            "n": len(times)}


def main():
    with tempfile.TemporaryDirectory() as td:
        paths = _build_dataset(Path(td))
        eng = OperationalSearchEngine(
            paths=paths,
            now=datetime(2026, 8, 13, 12, 30, tzinfo=timezone.utc))
        sources = {
            SearchSource.GATEWAY_LOG: "routine",
            SearchSource.EVENTS: "TOOL_STARTED",
            SearchSource.SCHEDULER: "report",
            SearchSource.PROVIDER: "provider",
            SearchSource.INTEGRATION: "platform",
        }
        print("=== Sprint 1.2.2 §24 benchmark (1000 searches/adapter) ===")
        for src, q in sources.items():
            res = _bench(lambda: eng.search(SearchRequest(
                query=q, source=src, limit=20)))
            print(f"  {src.value:14s} {res}")
        # Router decision p95 (§24: p95 < 5ms).
        router = IntentRouter(
            flags={"enabled": True,
                   "mode": RouterMode.ENFORCE_STATUS_READ.value},
            health_provider=lambda: {"status": "healthy"})
        queries = ["найди последние ошибки gateway",
                   "покажи события Hermes за час",
                   "search recent scheduler failures"]
        times = []
        for _ in range(1000):
            for q in queries:
                t0 = time.perf_counter()
                router.enforce(features_from_text(q, request_id="b"),
                               text=q)
                times.append((time.perf_counter() - t0) * 1000.0)
        print("  router decision:",
              {"p50": round(_percentile(times, 50), 3),
               "p95": round(_percentile(times, 95), 3),
               "max": round(max(times), 3),
               "n": len(times)})
        # §25 — redaction proof over synthetic secrets.
        outcome = eng.search(SearchRequest(
            query="fake", source=SearchSource.GATEWAY_LOG, limit=50))
        leaked = 0
        for r in outcome.results:
            for secret in ("sk-fake-openai", "fakebearer-token",
                           "Sup3rFake!Passw0rd", "sk-fake-key-9876543210",
                           "fake-client-secret-xyz"):
                if secret in r.summary:
                    leaked += 1
        print("=== §25 security fixtures ===")
        print(f"  results={len(outcome.results)} secret leaks={leaked}")


if __name__ == "__main__":
    main()
