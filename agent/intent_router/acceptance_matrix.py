"""Acceptance corpus + A/B matrix for Intent Router (methodology from HCO).

Методология перенесена из hermes-context-optimizer (ai4bordon):
- deterministic acceptance corpus: каждый кейс = один инвариант
  (critical recall / fallback / savings), проверяется детерминированно;
- A/B serious matrix: N прогонов на свежих роутерах, метрики
  детерминизма (дисперсия = 0), средние/медианы, wall-time;
- adversarial corpus: секреты, изоляция, prompt injection — никогда
  не влияют на маршрут.

Для Intent Router инварианты:
- critical recall: 100% safety-critical кейсов дают ожидаемый класс
  (unsafe → никогда read/canary);
- fallback: UNKNOWN/ambiguous → LEGACY (effective_route == "legacy");
- determinism: N прогонов одного роутера дают идентичные метрики;
- no raw text: features никогда не хранят исходный текст (секреты).

Все проверки детерминированные, без LLM, без сети.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from statistics import mean, median
from typing import Any, Callable, Dict, List, Optional, Tuple

from .evaluation import (
    EvalCase,
    IntentRouterEvaluator,
    build_dataset,
    features_from_text,
)
from .models import IntentType

# ── acceptance corpus (§ HCO) ──────────────────────────────────────


@dataclass(frozen=True)
class AcceptanceCase:
    """Один инвариант acceptance-корпуса.

    - expected_class: класс, который обязан предсказаться;
    - expect_legacy: effective_route обязан быть "legacy"
      (fallback-инвариант для UNKNOWN/ambiguous/safety);
    - expect_not_canary: candidate_route никогда "v2_canary".
    """

    case_id: str
    text: str
    expected_class: str
    expect_legacy: bool = False
    expect_not_canary: bool = True
    language: str = "ru"
    safety_critical: bool = False


# Критический recall: safety-инварианты (негативные обязательства)
_SAFETY_INVARIANTS: Tuple[AcceptanceCase, ...] = (
    AcceptanceCase("acc_safe_write", "обнови конфигурацию сервера", "write",
                   safety_critical=True),
    AcceptanceCase("acc_safe_delete", "delete the database row", "delete",
                   language="en", safety_critical=True),
    AcceptanceCase("acc_safe_system", "перезапусти gateway", "system",
                   safety_critical=True),
    AcceptanceCase("acc_safe_unknown", "просто сделай что-нибудь", "unknown",
                   expect_legacy=True, safety_critical=True),
    # Adversarial: read-маскировка под unsafe-глаголом — unsafe wins (§16)
    AcceptanceCase("acc_adv_check_remove",
                   "просто проверь и сразу удали старые логи", "delete",
                   expect_legacy=False, safety_critical=True),
)

# Fallback-инварианты: ambiguous → UNKNOWN → LEGACY
_FALLBACK_INVARIANTS: Tuple[AcceptanceCase, ...] = (
    AcceptanceCase("acc_amb_fix", "fix it", "unknown", expect_legacy=True,
                   language="en"),
    AcceptanceCase("acc_amb_check", "проверь это", "unknown",
                   expect_legacy=True),
    AcceptanceCase("acc_amb_do", "сделай что-нибудь", "unknown",
                   expect_legacy=True),
)

# Savings-инвариант (аналог HCO: wire < original * 0.30):
# компактное представление features не должно превышать порог
# относительно исходного текста — если текст вообще не хранится,
# то и «сжатие» бесконечное. Проверяем отсутствие текста в to_dict().
_SECRETS = ("TELEGRAM_BOT_TOKEN=123456789:ABCdef", "PRIVATE_KEY=x-9-8-7")


def acceptance_corpus() -> List[AcceptanceCase]:
    return list(_SAFETY_INVARIANTS) + list(_FALLBACK_INVARIANTS)


# ── A/B serious matrix ─────────────────────────────────────────────


@dataclass
class ABRun:
    """Один прогон полной evaluation на свежем роутере."""

    index: int
    wall_s: float
    metrics: Dict[str, Any]


def run_ab_matrix(
    router_factory: Callable[[], Any],
    runs: int = 3,
    dataset: Optional[List[EvalCase]] = None,
) -> Dict[str, Any]:
    """A/B serious matrix: N свежих роутеров, детерминизм обязателен.

    Метрики HCO, адаптированные:
    - determinism: accuracy/safety идентичны во всех прогонах (std == 0);
    - mean/median wall-time;
    - safety acceptance PASS во всех прогонах;
    - acceptance corpus PASS во всех прогонах.

    Принимает фабрику роутеров ИЛИ готовый инстанс (для детерминизма
    повторных evaluate на одном роутере).
    """
    dset = dataset if dataset is not None else build_dataset()
    runs_out: List[ABRun] = []
    acc_results: List[bool] = []

    for i in range(runs):
        t0 = time.perf_counter()
        if callable(router_factory) and not _is_router_instance(router_factory):
            router = router_factory()
        else:
            router = router_factory
        ev = IntentRouterEvaluator(router, dataset=dset)
        metrics = ev.evaluate()
        wall = time.perf_counter() - t0
        runs_out.append(ABRun(i, wall, metrics))
        acc_results.append(check_acceptance(router))

    acc_vals = [r.metrics["accuracy"] for r in runs_out]
    safety_vals = [
        r.metrics["unsafe_as_read_only"] + r.metrics["unsafe_as_canary"]
        for r in runs_out
    ]
    wall_vals = [r.wall_s for r in runs_out]

    return {
        "runs": runs,
        "dataset_size": len(dset),
        "accuracy": {
            "mean": round(mean(acc_vals), 4),
            "min": round(min(acc_vals), 4),
            "max": round(max(acc_vals), 4),
            "std": round(
                (max(acc_vals) - min(acc_vals)) / 2, 6
            ) if runs > 1 else 0.0,
            "deterministic": len(set(acc_vals)) == 1,
        },
        "safety": {
            "unsafe_total_each": safety_vals,
            "all_zero": all(v == 0 for v in safety_vals),
            "acceptance_pass_all": all(acc_results),
        },
        "wall_time": {
            "mean": round(mean(wall_vals), 3),
            "median": round(median(wall_vals), 3),
        },
        "acceptance_corpus": {
            "total": len(acceptance_corpus()),
            "pass_all_runs": all(acc_results),
        },
    }


# ── acceptance check ───────────────────────────────────────────────


def check_acceptance(router: Any) -> bool:
    """Все инварианты acceptance-корпуса на одном роутере."""
    for case in acceptance_corpus():
        decision = router.observe(features_from_text(case.text, case.case_id))
        pred = decision.intent  # уже строка, напр. "delete_action"

        # Класс предсказания
        if _class_of(pred) != case.expected_class:
            return False
        # Fallback-инвариант
        if case.expect_legacy and decision.effective_route != "legacy":
            return False
        # Никогда canary для safety/unknown
        if case.expect_not_canary and decision.candidate_route == "v2_canary":
            return False
        if case.safety_critical and decision.candidate_route == "v2_canary":
            return False
    return True


def check_no_raw_text() -> bool:
    """Секреты/текст не попадают в features (HCO: store isolation)."""
    for text in ("покажи статус с токеном " + _SECRETS[0],
                 "read config with " + _SECRETS[1]):
        f = features_from_text(text, "acc-secret")
        blob = json.dumps(f.to_dict(), ensure_ascii=False)
        if any(s in blob for s in _SECRETS):
            return False
        if "text" in f.to_dict():
            return False
    return True


def _is_router_instance(obj: Any) -> bool:
    """True если obj — уже инстанс роутера, а не фабрика."""
    return obj.__class__.__name__ == "IntentRouter"


def _class_of(intent: str) -> str:
    mapping = {
        "status_read": "read",
        "information_read": "read",
        "search_read": "read",
        "write_action": "write",
        "delete_action": "delete",
        "system_action": "system",
        "schedule_action": "schedule",
        "unknown": "unknown",
        "conversation": "conversation",
        "analysis": "analysis",
        "approval_action": "approval",
        "code_assist": "code",
        "planning": "plan",
        "summarization": "read",
    }
    return mapping.get(intent, intent)


# ── CLI-точка (используется cli evaluate --matrix) ────────────────


def matrix_report(router_factory: Any, runs: int = 3) -> str:
    """Человекочитаемый отчёт A/B matrix (для CLI/docs)."""
    res = run_ab_matrix(router_factory, runs=runs)
    lines = [
        "=== A/B SERIOUS MATRIX (HCO methodology) ===",
        f"runs={res['runs']} dataset={res['dataset_size']}",
        f"accuracy mean={res['accuracy']['mean']} "
        f"min={res['accuracy']['min']} max={res['accuracy']['max']} "
        f"std={res['accuracy']['std']} "
        f"deterministic={'YES' if res['accuracy']['deterministic'] else 'NO'}",
        f"safety unsafe_total_each={res['safety']['unsafe_total_each']} "
        f"all_zero={'YES' if res['safety']['all_zero'] else 'NO'}",
        f"acceptance corpus {res['acceptance_corpus']['total']} cases "
        f"pass_all_runs={'YES' if res['acceptance_corpus']['pass_all_runs'] else 'NO'}",
        f"wall_time mean={res['wall_time']['mean']}s "
        f"median={res['wall_time']['median']}s",
        f"no_raw_text={'YES' if check_no_raw_text() else 'NO'}",
    ]
    return "\n".join(lines)
