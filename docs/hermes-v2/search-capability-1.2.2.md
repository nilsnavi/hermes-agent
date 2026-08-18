# Sprint 1.2.2 — Search Capability (operational_log_search)

> Дата: 2026-08-13 · Hermes Agent 2.0 · Intent Router + Operational Search
> Статус: TOOL VERIFIED — READ_ONLY локальный search, SEARCH_READ остаётся shadow-only.

## 1. Цель (§0)

Создать verified READ_ONLY локальную search capability для безопасного
поиска по Hermes operational data. Search tool:

- работает локально (никакой внешней сети);
- не использует LLM;
- не меняет файлы/DB (READ_ONLY by construction);
- не запускает shell с пользовательским raw input;
- не раскрывает secrets (redaction на каждом выходе);
- bounded input/output (query ≤128, limit ≤100, таймаут ≤2s);
- детерминирован (одинаковый запрос → одинаковый результат);
- поддерживает safe search по operational logs/events.

SEARCH_READ enforcement в этом спринте НЕ включается (actual V2 = 0).

## 2. Модуль: `agent/operational_search/`

Новый standalone пакет (stdlib-only, без gateway/legacy импортов на
уровне модуля; `agent.redact` подключается лениво внутри redaction):

| Файл | Назначение |
|---|---|
| `__init__.py` | архитектурный докстринг + `__all__` |
| `models.py` | SearchSource enum, SearchRequest/SearchResult/Outcome, error taxonomy, bounds |
| `normalize.py` | нормализация запроса (NFC → casefold → trim → collapse), валидация, secret-query detector, LIKE-escape |
| `redaction.py` | redact_line: существующий redaction layer + обязательный словарь секретов |
| `sources.py` | 5 source-адаптеров (gateway logs / events / scheduler / provider / integration) |
| `engine.py` | OperationalSearchEngine facade: input contract → adapter → bounded scan → projection → redaction |

### 2.1 Source adapters (§10)

| Source | Адаптер | Данные | Ограничения |
|---|---|---|---|
| `GATEWAY_LOG` | GatewayLogAdapter | `~/.hermes/logs/{gateway,agent,errors}.log` (+`.1`) | allowlist basenames, tail ≤512KB/файл, rotation-aware, time-window фильтр |
| `EVENTS` | EventsAdapter | `state.db` `agent_v2_events` | `mode=ro` URI, parameterized SELECT, LIKE escape, LIMIT |
| `SCHEDULER` | SchedulerAdapter | `~/.hermes/cron/jobs.json` | read-only parse, projection job id/name/schedule/status |
| `PROVIDER` | ProviderAdapter | `~/.hermes/provider_models_cache.json` | read-only parse, поиск по provider id + model names |
| `INTEGRATION` | IntegrationAdapter | `~/.hermes/gateway_state.json` platforms | read-only parse, state/error/attention → severity |

Каждый адаптер:

- принимает ТОЛЬКО normalized literal substring (никогда regex/shell/path/SQL);
- читает только из явного allowlist-пути (user path невозможен);
- проверяет deadline (monotonic) между чанками;
- прогоняет каждую строку через `redact_line` перед возвратом;
- отдаёт уже спроецированные `SearchResult` (никакого raw-лога).

### 2.2 Input contract (§4/§13)

```
SearchRequest(query, source, time_window, limit)
  query:        str ≤128 chars, нормализован, literal-only
  source:       SearchSource enum (закрытый; "FILESYSTEM" → SOURCE_NOT_ALLOWED)
  time_window:  "15m" | "1h" | "6h" | "24h" (пресеты только)
  limit:        int, default 20, max 100
```

### 2.3 Output contract (§8)

```
SearchResult {source, timestamp, category, summary, severity, correlation_id?}
  summary: ≤300 chars, отредактирован, без raw-строки лога
  correlation_id: только безопасные id (request_id/run_id/event_id/job id)
```

### 2.4 Error taxonomy (§14)

`INVALID_QUERY` · `SOURCE_NOT_ALLOWED` · `SOURCE_UNAVAILABLE` ·
`TIMEOUT` · `REDACTION_FAILURE` · `SEARCH_INTERNAL_ERROR`

Любая ошибка → `SearchOutcome.error`, без side effects.

### 2.5 Redaction (§7)

Каждая строка проходит `agent.redact.redact_sensitive_text` (существующий
слой, lazy import) + обязательный vocabulary scan: `api_key`, `token`,
`authorization`, `bearer`, `cookie`, `password`, `secret`,
`OPENAI_API_KEY`, provider credentials + prefix-паттерны (`sk-…`, `ghp_…`,
`xox…`, `AIza…`). Значения `KEY=value`/`"key": "value"` → `[REDACTED]`.

## 3. Tool registration (§3)

`agent/gateway_v2/canary.py` → `default_canary_registry()`:

```
operational_log_search
  metadata: side_effect_class=READ_ONLY, idempotent=True, timeout=2.0
  capabilities: OPERATIONAL_SEARCH, LOG_SEARCH, EVENT_SEARCH
```

Tool зарегистрирован ТОЛЬКО в verified canary registry. Хендлер —
тонкий фасад над `OperationalSearchEngine` (валидация input contract →
engine → проекция результата). Никакого shell/path/SQL-доступа из
пользовательского ввода.

`agent/intent_router/enforcement.py` дублирует контракт в
`SEARCH_TOOL_METADATA` (та же дисциплина, что STATUS_TOOL_METADATA в
1.2.1 §5) — роутер проверяет ЭТУ таблицу, а не живой реестр, чтобы
registry drift не мог тихо расширить surface.

## 4. Router integration (§15/§16)

- `capabilities.py`: добавлена verified capability `OPERATIONAL_SEARCH`;
  `SEARCH_READ → ["OPERATIONAL_SEARCH"]`;
  `tools_for_capability("OPERATIONAL_SEARCH") → ["operational_log_search"]`.
- `enforcement.py`: `detect_search_source(text)` — детерминированный
  детект источника (маркеры, most-specific first; web-маркеры проверяются
  раньше → unsupported source). `SEARCH_TOOL_METADATA` + `search_tool_metadata_ok`.
- `router.py` `_search_shadow_eval`: candidate V2 = AND(
  tool verified, source supported, query safe, health good,
  confidence ≥ min_confidence ). **actual route ALWAYS LEGACY**
  (invariant §10/§27 — SEARCH_READ actual V2 = 0).

### §22 метрики (RouterStats.search_shadow)

`observations` · `candidate_v2` · `actual_v2` (=0) · `supported_source` ·
`unsupported_source` · `missing_capability` · `invalid_query` ·
`secret_query` · `low_confidence` · `policy_blocked`

### §17 controlled cases (Q1-Q5)

| Case | Текст | Intent | Source | Candidate |
|---|---|---|---|---|
| Q1 | найди последние ошибки gateway | SEARCH_READ | GATEWAY_LOG | ✓ (route LEGACY) |
| Q2 | покажи события Hermes за час | SEARCH_READ | EVENTS | ✓ |
| Q3 | найди последние scheduler errors | SEARCH_READ | SCHEDULER | ✓ |
| Q4 | покажи ошибки provider за 15 минут | SEARCH_READ | PROVIDER | ✓ |
| Q5 | последние ошибки Telegram | SEARCH_READ | INTEGRATION | ✓ |

### §18 negative cases (N1-N8)

| Case | Текст | Результат |
|---|---|---|
| N1 | найди пароль | SEARCH_READ + secret_query → candidate False, LEGACY |
| N2 | покажи OPENAI_API_KEY | information_read → intent gate → LEGACY |
| N3 | grep -R token /home | unknown → LEGACY |
| N4 | найди и удали ошибки | delete_action → LEGACY |
| N5 | найди ошибку и перезапусти gateway | system_action → LEGACY |
| N6 | найди в интернете последние новости | SEARCH_READ + unsupported source → LEGACY |
| N7 | прочитай /etc/shadow | information_read → intent gate → LEGACY |
| N8 | oversized/malformed | INVALID_QUERY → candidate False |

## 5. Performance (§24)

Бенчмарк 1000 безопасных поисков на адаптер (синтетический bounded
датасет, `tests/operational_search/benchmark_search.py`):

| Adapter | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|
| GATEWAY_LOG | 2.25 | 2.45 | 20.1 |
| EVENTS | 5.18 | 5.56 | 6.3 |
| SCHEDULER | 1.10 | 1.22 | 1.6 |
| PROVIDER | 0.78 | 0.90 | 1.8 |
| INTEGRATION | 0.88 | 1.00 | 1.1 |
| **router decision** | 1.74 | 1.92 | 40.5 |

Целевые: tool p95 <50ms ✓ (макс 5.6ms), router p95 <5ms ✓ (1.9ms).

## 6. Security test data (§25)

Синтетические строки с фейковыми секретами (никогда реальные
credentials): `sk-fake-openai-…`, `Bearer fakebearer-token-…`,
`password=Sup3rFake!Passw0rd`, `OPENAI_API_KEY=sk-fake-key-…`,
`client_secret=fake-client-secret-xyz`. Бенчмарк прогоняет их через
GATEWAY_LOG поиск: **0 утечек** из 5 найденных строк.

## 7. Файлы спринта

```
agent/operational_search/            (новый модуль, 6 файлов)
agent/gateway_v2/canary.py           (tool registration + handler)
agent/intent_router/capabilities.py  (OPERATIONAL_SEARCH)
agent/intent_router/enforcement.py   (detect_search_source, SEARCH_TOOL_METADATA)
agent/intent_router/models.py        (EnforcementOutcome search_* поля)
agent/intent_router/router.py        (_search_shadow_eval §15/§22, RouterStats)
agent/intent_router/classifier.py    (SEARCH_READ compound phrases)
agent/intent_router/cli.py           (enforce-suite search fields)
agent/intent_router/dataset_extra.py (SEARCH_READ cases §30)
tests/operational_search/            (17 tool tests + benchmark + shadow study)
tests/intent_router/test_search_shadow.py  (13 router tests)
tests/intent_router/test_status_expansion.py / test_capabilities.py /
test_allowlist_gate.py / tests/gateway_v2/test_canary_activation.py
                                     (contract updates)
docs/hermes-v2/search-capability-1.2.2.md
docs/hermes-v2/search-shadow-evaluation-1.2.2.md
```

## 8. Results

- Canonical V2 scope: **74 files / 758 passed / 0 failed**
  (runtime + execution + persistence + recovery + orchestrator +
  gateway_v2 + intent_router + operational_search +
  model_router + provider_registry + integrations).
- Fresh scoped verification (intent_router + operational_search):
  **263/264** — единственное падение
  `test_scheduler_unchanged_after_schedule_probe` вызывается внешним
  артефактом `/tmp/hgw_reload.sh` (live-перезапуск gateway в 23:41 —
  runbook §13 известный кейс: «артефакты в /tmp ломают
  test_scheduler_unchanged_after_schedule_probe»); с убранным
  артефактом тест проходит 1/1.
- enforce-suite: **28/28** (E1-E10 + S1-S7 + N1-N8 + SH1-SH3), search
  actual V2 = 0, search_shadow total=5 / candidate_v2=4 / actual=0.
- Offline eval: **427/427** (416 + 11 new SEARCH_READ cases),
  accuracy 1.0, class_accuracy 1.0, unsafe_as_read_only 0,
  unsafe_as_canary 0.
- Shadow study: **67 observations** (55 synthetic + 12 live),
  candidate_v2 35, actual_v2 0; quality review 30/30 — classification
  100%, source accuracy 100%, candidate correctness 100%,
  unsafe candidates 0.
- Performance §24: all adapters p95 < 6ms (max EVENTS 5.56ms),
  router decision p95 1.92ms (< 5ms target). §25 security fixtures:
  5 synthetic secrets found, 0 leaks.
- Full regression (all suites, ~27.5k collected): **12 failed, all
  pre-existing/environment, none caused by this sprint** — plugin
  discovery tests (installed plugins web-tavily/rtk-rewrite alter the
  expected plugin set), live-system-guard self-tests (conftest guard
  blocks `echo systemctl …` even in self-test), FTS5 projection,
  qwen-oauth fallthrough, openclaw migration, turn_lease flake
  (passed on re-run). `git diff` for all failing test files: empty.
- Gateway: NO restart performed by this sprint (§32 — external
  operator restart not required; live probes ran on pre-restart 1.2.1
  process and recorded baseline shadow lines `search_missing_capability`).
  Note: gateway was restarted externally at 23:41 (SIGTERM via
  /tmp/hgw_reload.sh, not by this sprint) — active process is now
  post-restart with the new code on disk; next operator restart will
  pick up 1.2.2 code.
