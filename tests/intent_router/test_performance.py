"""Performance tests (Sprint 1.1 §58-59)."""

import time

from agent.intent_router.evaluation import features_from_text
from agent.intent_router.router import IntentRouter

_TEXTS = [
    "покажи статус сервера",
    "удали файл",
    "сделай это",
    "show server status",
    "напомни завтра",
    "перезапусти gateway",
    "проанализируй продажи",
    "привет",
    "отправь сообщение",
    "найди информацию",
]


def _router():
    return IntentRouter(
        flags={"enabled": True, "mode": "observe",
               "canary": True, "shadow": True},
        health_provider=lambda: {"status": "healthy"},
    )


def test_10k_decisions_performant():
    r = _router()
    r.observe(features_from_text("warm", "warm", internal=True))  # warm cache
    n = 10000
    t0 = time.perf_counter()
    for i in range(n):
        r.observe(features_from_text(
            _TEXTS[i % len(_TEXTS)], f"r{i}",
            internal=(i % 5 == 0)))
    elapsed = time.perf_counter() - t0
    per = elapsed / n * 1000.0
    # deterministic evaluation: well under 5 ms/decision.
    assert per < 5.0, f"{per:.3f} ms/decision too slow"
    assert r.stats()["errors"] == 0


def test_observe_adds_negligible_latency():
    r = _router()
    r.observe(features_from_text("warm", "warm"))
    n = 1000
    t0 = time.perf_counter()
    for i in range(n):
        r.observe(features_from_text("покажи статус", f"r{i}"))
    elapsed = time.perf_counter() - t0
    per = elapsed / n * 1000.0
    assert per < 5.0


def test_no_thread_creation():
    import threading

    r = _router()
    before = threading.active_count()
    for _ in range(50):
        r.observe(features_from_text("покажи статус", "r"))
    assert threading.active_count() == before
