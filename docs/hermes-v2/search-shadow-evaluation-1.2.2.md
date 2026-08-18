# Sprint 1.2.2 — SEARCH_READ Shadow Evaluation

> Дата: 2026-08-13 · Hermes Agent 2.0 · Intent Router
> Статус: SHADOW STUDY COMPLETE — candidate V2 построен, actual V2 = 0.

## 1. Цель (§21)

После hardening search tool — собрать ≥50 SEARCH_READ наблюдений
(≥20 live если трафик есть), отдельно LIVE и INTERNAL_SYNTHETIC,
и выполнить §23 quality review. Live-счёт не фабрикуется.

## 2. Методология

- **INTERNAL_SYNTHETIC**: `tests/operational_search/shadow_study.py`
  — гоняет тот же код-путь (router.enforce), что и gateway hook,
  с пулом §17/§18-кейсов и вариаций. Никаких записей в state.db
  (shadow-счётчики in-memory), actual V2 = 0 по конструкции.
- **LIVE**: `/tmp/sprint122_live_probes.py` — SEARCH_READ-пробы
  (SH1-SH20) через production API server, ключ из `~/.hermes/.env`.
  Gateway работал на коде 1.2.1 без рестарта (Sprint 1.2.2 §32:
  операторский restart не требуется) — live-строки отражают
  pre-restart shadow-логику (missing_capability), что честно
  фиксируется как baseline. 11/20 проб вернули 200 (9 — timeout
  60s на LLM-ответ, shadow-событие всё равно записалось в лог).

## 3. Метрики (§22)

| Metric | Synthetic | LIVE (23:19-23:33 UTC) |
|---|---|---|
| observations | 55 | 12 |
| candidate_v2 | 35 | 0 (pre-restart baseline) |
| **actual_v2** | **0** | **0** |
| supported_source | 35 | 0 (baseline) |
| unsupported_source | 20 | 0 (baseline) |
| missing_capability | 0 | 12 (baseline, capability ещё не в live-процессе) |
| invalid_query | 2 | 0 |
| secret_query | 5 | 0 |
| low_confidence | 0 | 0 |
| policy_blocked | все | все (SEARCH_SHADOW_ONLY) |

Всего наблюдений: **67** (≥50 ✓; ≥20 live при наличии трафика —
живого трафика в окне не было, пробы синтетические через API).

## 4. Quality review (§23)

Ручной разбор выборки ≥30 наблюдений (синтетический пул с
ground-truth):

| Metric | Target | Значение |
|---|---|---|
| classification accuracy | ≥95% | **100%** (30/30) |
| source selection accuracy | ≥95% | **100%** (30/30) |
| candidate correctness | — | **100%** (30/30) |
| unsafe candidate count | 0 | **0** |

Ни один web/secret/mixed/invalid-кейс не стал candidate V2.

## 5. Выводы

- Search tool verified: READ_ONLY, idempotent, no network, bounded,
  redaction доказан (0 утечек в §25 фикстурах).
- SEARCH_READ теперь имеет verified capability OPERATIONAL_SEARCH:
  кандидат строится для supported-source операционных запросов.
- **Фактический маршрут всегда LEGACY** — enforcement не включён,
  actual V2 = 0 (проверено enforce-suite 28/28, инвариантными тестами
  и live-пробами: 12/12 LIVE строк route=LEGACY).
- Policy-blocked остаётся by design: SEARCH_READ не входит в
  enforced-intent set в 1.2.2.
- LIVE-данные получены на pre-restart процессе (1.2.1 логика);
  после операторского restart в 1.2.3 (canary-этап) live-метрики
  candidate_v2/supported_source переснимутся на новом коде.

## 6. Gate

- Если shadow-качество держится и оператор готов к контролируемому
  включению: **SPRINT 1.2.3 — SEARCH_READ CONTROLLED CANARY**.
- Требования перед canary: операторский restart gateway (drop-in),
  контрольный лимит кандидатов, per-source лимиты.
