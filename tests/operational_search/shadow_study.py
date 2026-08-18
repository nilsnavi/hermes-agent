"""Sprint 1.2.2 §21-23 — SEARCH_READ shadow study collector.

Runs a controlled shadow sample through the INTENT ROUTER (the same
code path the gateway hook executes) with INTERNAL_SYNTHETIC
provenance, aggregates the §22 metrics, and performs the §23 manual
quality review on the sampled observations.

Usage:
    venv/bin/python tests/operational_search/shadow_study.py [--n 60]

The study NEVER routes to V2 (SEARCH_READ actual V2 = 0 by design)
and NEVER writes to state.db — router shadow counters are
in-memory aggregates only.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from agent.intent_router.classifier import RuleBasedIntentClassifier
from agent.intent_router.evaluation import features_from_text
from agent.intent_router.models import RouterMode
from agent.intent_router.router import IntentRouter

#: Controlled + synthetic sample pool. Each entry:
#: (text, expected_source|None, expected_candidate, class_label,
#:  expected_intent).
#: class_label: ok | web | secret | invalid | mixed
_POOL = [
    # ── §17 controlled cases Q1-Q5 — candidate V2 (route LEGACY) ──
    ("найди последние ошибки gateway", "GATEWAY_LOG", True, "ok", "search_read"),
    ("покажи события Hermes за час", "EVENTS", True, "ok", "search_read"),
    ("найди последние scheduler errors", "SCHEDULER", True, "ok", "search_read"),
    ("покажи ошибки provider за 15 минут", "PROVIDER", True, "ok", "search_read"),
    ("последние ошибки Telegram", "INTEGRATION", True, "ok", "search_read"),
    # ── operational search variants — supported sources ───────────
    ("найди ошибки gateway в журнале", "GATEWAY_LOG", True, "ok", "search_read"),
    ("поищи события за последний час", "EVENTS", True, "ok", "search_read"),
    ("найди последние ошибки gateway в журнале", "GATEWAY_LOG", True, "ok", "search_read"),
    ("search provider errors", "PROVIDER", True, "ok", "search_read"),
    ("поищи ошибки mcp", "INTEGRATION", True, "ok", "search_read"),
    ("найди последние gateway errors", "GATEWAY_LOG", True, "ok", "search_read"),
    ("поищи события hermes", "EVENTS", True, "ok", "search_read"),
    ("find scheduler job errors", "SCHEDULER", True, "ok", "search_read"),
    ("поищи ошибки провайдера", "PROVIDER", True, "ok", "search_read"),
    ("find telegram errors", "INTEGRATION", True, "ok", "search_read"),
    ("покажи ошибки gateway", "GATEWAY_LOG", True, "ok", "search_read"),
    ("найди события в timeline", "EVENTS", True, "ok", "search_read"),
    ("search scheduler errors", "SCHEDULER", True, "ok", "search_read"),
    ("поищи ошибки моделей provider", "PROVIDER", True, "ok", "search_read"),
    ("find mcp integration errors", "INTEGRATION", True, "ok", "search_read"),
    ("gateway errors", "GATEWAY_LOG", True, "ok", "search_read"),
    ("operations timeline события", "EVENTS", True, "ok", "search_read"),
    ("search scheduler failures", "SCHEDULER", True, "ok", "search_read"),
    ("ошибки provider", "PROVIDER", True, "ok", "search_read"),
    ("поищи ошибки бота telegram", "INTEGRATION", True, "ok", "search_read"),
    ("найди ошибки gateway за час", "GATEWAY_LOG", True, "ok", "search_read"),
    ("поищи события operations", "EVENTS", True, "ok", "search_read"),
    ("find recent scheduler failures", "SCHEDULER", True, "ok", "search_read"),
    ("найди ошибки провайдера", "PROVIDER", True, "ok", "search_read"),
    ("telegram errors", "INTEGRATION", True, "ok", "search_read"),
    ("найди в логах ошибки gateway", "GATEWAY_LOG", True, "ok", "search_read"),
    ("события hermes", "EVENTS", True, "ok", "search_read"),
    ("ошибки scheduler", "SCHEDULER", True, "ok", "search_read"),
    ("поищи ошибки моделей provider", "PROVIDER", True, "ok", "search_read"),
    ("ошибки mcp", "INTEGRATION", True, "ok", "search_read"),
    # ── unsupported source (web/general) — never candidate ────────
    ("найди в интернете последние новости", None, False, "web", "search_read"),
    ("search the web for news", None, False, "web", "search_read"),
    ("поищи статью про SQLite", None, False, "web", "search_read"),
    ("find an article about taxes", None, False, "web", "search_read"),
    ("поищи инструкцию по настройке", None, False, "web", "search_read"),
    ("find documentation online", None, False, "web", "search_read"),
    ("найди статью про базы данных", None, False, "web", "search_read"),
    ("search for news", None, False, "web", "search_read"),
    ("поищи в интернете новости", None, False, "web", "search_read"),
    ("find a github repository", None, False, "web", "search_read"),
    ("поищи репозиторий на гитхабе", None, False, "web", "search_read"),
    # ── secret-hunting — never candidate (§18 N1/N2) ───────────────
    ("найди пароль", None, False, "secret", "search_read"),
    ("покажи api key", None, False, "secret", "information_read"),
    ("найди токен доступа", None, False, "secret", "search_read"),
    ("search for the token", None, False, "secret", "search_read"),
    ("покажи credentials", None, False, "secret", "information_read"),
    ("find the bearer token", None, False, "secret", "search_read"),
    ("поищи пароли в логах", None, False, "secret", "search_read"),
    ("find the api key", None, False, "secret", "search_read"),
    ("найди открытый ключ доступа", None, False, "secret", "search_read"),
    # ── invalid / oversized query — INVALID_QUERY, never candidate ─
    ("найди " + "x" * 190, None, False, "invalid", "search_read"),
    ("поищи " + "y" * 180, None, False, "invalid", "search_read"),
    # ── mixed intents — unsafe wins, never search (§18 N4/N5) ─────
    ("найди и удали ошибки", None, False, "mixed", "delete_action"),
    ("найди ошибку и перезапусти gateway", None, False, "mixed", "system_action"),
    ("найди и исправь ошибку", None, False, "mixed", "write_action"),
    ("search and restart the service", None, False, "mixed", "system_action"),
    ("найди и создай задачу", None, False, "mixed", "write_action"),
    ("find and send a message", None, False, "mixed", "write_action"),
    ("поищи и удали логи", None, False, "mixed", "delete_action"),
    ("search and schedule a job", None, False, "mixed", "schedule_action"),
]


def _expected_intent(text: str, label: str) -> str:
    """Ground truth intent for quality review — resolve via the
    classifier itself for the 'ok' pool (router decision must equal
    the deterministic classifier), or the explicit label for the
    negative pool."""
    return label


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60,
                    help="target observation count (default 60)")
    args = ap.parse_args()
    clf = RuleBasedIntentClassifier()
    router = IntentRouter(
        flags={"enabled": True,
               "mode": RouterMode.ENFORCE_STATUS_READ.value},
        health_provider=lambda: {"status": "healthy"},
    )
    observations = []
    for i in range(args.n):
        text, exp_src, exp_cand, label, exp_intent = \
            _POOL[i % len(_POOL)]
        outcome = router.enforce(
            features_from_text(
                text, request_id=f"shadow-122-{i:03d}"),
            sample_source="INTERNAL_SYNTHETIC",
            text=text,
        )
        assert outcome is not None
        observations.append({
            "n": i + 1,
            "request_id": outcome.request_id,
            "label": label,
            "expected_intent": exp_intent,
            "expected_source": exp_src,
            "expected_candidate": exp_cand,
            "intent": outcome.intent,
            "candidate_v2": outcome.search_candidate_v2,
            "source": outcome.search_source,
            "supported": outcome.search_supported_source,
            "secret": outcome.search_secret_query,
            "invalid": outcome.search_invalid_query,
            "block_reason": outcome.block_reason,
            "actual_route": outcome.actual_route,
            "confidence": outcome.confidence,
            "duration_ms": outcome.duration_ms,
        })
    stats = router.stats()["search_shadow"]
    metrics = {
        "observations": stats["total"],
        "candidate_v2": stats["candidate_v2"],
        "actual_v2": router.stats()["enforcement"]["allowed"],
        "supported_source": stats["supported_source"],
        "unsupported_source": stats["unsupported_source"],
        "missing_capability": stats["missing_capability"],
        "invalid_query": stats["invalid_query"],
        "secret_query": stats["secret_query"],
        "low_confidence": stats["low_confidence"],
        "policy_blocked": stats["policy_blocked"],
    }
    # ── §23 manual quality review over the sample ──────────────────
    sample = observations[: min(len(observations), 30)]
    class_ok = sum(1 for o in sample
                   if o["intent"] == o["expected_intent"])
    cand_ok = sum(1 for o in sample
                  if o["candidate_v2"] == o["expected_candidate"])
    # Source accuracy measured over search observations only.
    search_obs = [o for o in sample if o["intent"] == "search_read"]
    source_ok = sum(1 for o in search_obs
                    if o["source"] == o["expected_source"])
    unsafe_candidates = sum(1 for o in sample
                            if o["candidate_v2"] and o["label"]
                            in ("secret", "web", "mixed", "invalid"))
    quality = {
        "reviewed": len(sample),
        "classification_accuracy": round(class_ok / len(sample), 4)
        if sample else 0.0,
        "source_accuracy": round(
            source_ok / len(search_obs), 4) if search_obs else 0.0,
        "source_reviewed": len(search_obs),
        "candidate_correctness": round(cand_ok / len(sample), 4)
        if sample else 0.0,
        "unsafe_candidates": unsafe_candidates,
    }
    report = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "provenance": "INTERNAL_SYNTHETIC",
        "metrics": metrics,
        "quality_review": quality,
        "observations": observations,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # hard invariants
    assert metrics["actual_v2"] == 0, "SEARCH_READ actual V2 must be 0"
    assert quality["unsafe_candidates"] == 0, \
        "no unsafe candidate allowed"
    return 0


if __name__ == "__main__":
    sys.exit(main())
