# Agent Orchestration Framework Hermes 2.0 — Phase 3
## Memory Intelligence Platform (memory control plane)

> **Статус:** реализовано. Дата: 2026-08-25
> Репозиторий: `~/.hermes/hermes-agent-sprint137` · ветка `sprint/1.3.7-narrow-production-canary`
> Head: `9389dea5…` (не менялся) · Pre-change backup: `~/hermes-backup-sprint-1.4-phase3-memory-20260825-224427` (957/957 OK)

---

## 0. Scope Phase 3 (реализовано)

Новый изолированный пакет `agent/platform_memory/` (аналогично platform_policy/persistence/api),
без правки production `agent/memory_provider.py` / `agent/memory_manager.py`.

| # | Scope item | Модуль | Статус |
|---|---|---|---|
| 1 | Unified Memory Gateway | `memory_gateway.py` (`UnifiedMemoryGateway`) | ✅ новый |
| 2 | Memory Provider interface | `memory_provider.py` (`MemoryProvider` seam) | ✅ |
| 3 | Retrieval pipeline | `retrieval.py` (`RetrievalPipeline`) | ✅ |
| 4 | Memory scopes | `memory_scopes.py` (`MemoryScope`, `MemoryAccess`, `MemoryKey`) | ✅ |
| 5 | Storage backends abstraction | `storage_backends.py` (ShortTerm/AuthorityWork/LongTerm/Semantic seams) | ✅ |
| 6 | Memory lifecycle | `memory_lifecycle.py` (`MemoryLifecycle`) | ✅ |
| 7 | Remember/Forget/Consolidate | `memory_workflows.py` | ✅ |
| 8 | Provenance tracking | `provenance.py` (`ProvenanceRecord`) | ✅ |
| 9 | Memory security filtering | `memory_security.py` (redaction + injection sanitation) | ✅ |

Все модули — pure contracts / stdlib-only / без execution-импортов / без authority.

---

## 1. Unified Memory Gateway + MemoryProvider (items 1-2)

- `MemoryProvider` — единственный seam: `remember/forget/read`. Новый memory интегрируется
  только через него; остальное никогда не достаёт до storage напрямую.
- `UnifiedMemoryGateway` — фасад над provider + retrieval + workflows. **DATA-only**:
  `is_authority is False`; нет grant/execute/approve_execution. Каждая операция привязана
  к явному `MemoryAccess` (tenant+user).

## 2. Retrieval pipeline (item 3)

Строгий порядок безопасности (перед моделью):
`tenant scope` → `permission filter` → `redaction` → `injection sanitation` → `similarity` → `Top-K context`.
- tenant-привязка: `MemoryQuery.tenant_id` из `access`.
- permission filter: user-scope → только владелец (fail-closed, cross-user исключён).
- redaction: `redact_secrets` чистит bearer/api_key/password из итогового text.
- injection sanitation: `sanitize_payload` маркерный детект → item дропается (DATA-only, не передаётся).
- similarity: детерминированный word-overlap (pgvector seam подставляется на деплое).
- Top-K: bounded (1..32).

## 3. Memory scopes (item 4)

`MemoryScope` (GLOBAL/TENANT/USER). `MemoryKey.is_accessible_to(access)`:
- cross-tenant → всегда False;
- USER-scope → только равный user_id;
- TENANT/GLOBAL → любой член tenant.
`require_accessible` — fail-closed raiser.

## 4. Storage backends (item 5)

`ShortTermStore` (Redis), `AuthorityWorkStore`/`LongTermStore` (PostgreSQL),
`SemanticIndex` (pgvector). Все — **Protocol seams**, без реальных драйверов
(нет импорта redis/psycopg/httpx/socket/sqlite3). pgvector — только в docstring.

## 5. Memory lifecycle (item 6)

`MemoryLifecycleStatus`: CREATED→ACTIVE→CONSOLIDATED→(FORGOTTEN|RETIRED).
Терминальные (FORGOTTEN/RETIRED) иммутабельны; illegal → `InvalidMemoryTransition`;
consolidated не возвращается в ACTIVE (нет flapping). Чистая машина состояний.

## 6. Workflows (item 7)

- `RememberWorkflow` — write + provenance, валидация key/payload/provenance/access.
- `ForgetWorkflow` — требует существующий record, CREATED→ACTIVE→FORGOTTEN, затем forget.
- `ConsolidateWorkflow` — требует единый tenant+scope источников; derived provenance
  `generation+1`, source=CONSOLIDATION.

## 7. Provenance (item 8)

`ProvenanceRecord` (source/actor_id/created_at/generation) — immutable, обязателен на write.
`child()` — generation+1 для консолидации; timestamp validation. Записью без provenance невозможна(по построению API требует ProvenanceRecord).

## 8. Memory security filtering (item 9)

- `redact_secrets` — bearer/api_key/access_token/password (case-insensitive).
- `sanitize_payload` — детект directive-маркеров ("ignore previous instructions",
  "you are now", "system prompt:", "disregard", ...) → item помечается как не-инструкция
  (raise → pipeline дропает). **Injection treated as data.**

---

## 9. Архитектурная граница

- **Memory = DATA, не AUTHORITY** — ни один модуль не экспортирует authority-поверхность.
- **Memory не грантирует capabilities, не одобряет execution, не меняет policies, не обходит
  SystemBoundary** — нет grant/execute/approve/bypass нигде.
- **ИЗОЛЯЦИЯ**: platform_memory НЕ импортирует production `agent/memory_provider.py` /
  `agent/memory_manager.py` (проверено: реальные импорты только stdlib + sibling).
- **Нет второго execution engine** — 0 execution-kernel импортов во всех файлах.
- AST-скан: 0 authority-method defs (execute/grant/authorize/dispatch/bypass).
- Storage seams: только Protocol, без реальных драйверов.

## 10. Verification

- `compileall` — OK.
- Scoped canonical (`scripts/run_tests.sh tests/agent_runtime tests/agent_orchestration
  tests/platform_policy tests/platform_persistence tests/platform_api tests/platform_memory`):
  **332 passed / 0 failed** (28 файлов). Phase 3 добавил +37 (Phase 1+2 было 295).
- Production untouched: kernel + memory_provider/manager modified = NONE; HEAD не менялся.
- Полный canonical: см. "Регрессия".

## 11. Acceptance gates Phase 3

| Gate | Статус |
|---|---|
| memory never becomes authority | ✅ (is_authority False; 0 authority-методов) |
| tenant isolation verified | ✅ (is_accessible_to + require_accessible + record-boundary матрица в retrieval) |
| provenance exists | ✅ (обязательна на write; generation при consolidate) |
| retrieval cannot leak cross-user data | ✅ (record-boundary: tenant+user, fail-closed; regression-тесты) |
| injection payloads treated as data | ✅ (sanitize дропает; не передаётся в context) |
| lifecycle state machine verified | ✅ (fail-closed, терминальные иммутабельны, нет flapping) |
| Security review | ✅ (adversarial review: 1-й REQUEST_CHANGES (BLOCKING=2) → исправлено → пере-review BLOCKING=0 PASS) |
| NEW_REGRESSIONS=0 | ✅ (полный canonical: 0 phase-failures, 31 external pre-existing) |

## 12. Блокирующие находки 1-го review → исправлены

Первый независимый review нашёл 2 BLOCKING-дефекта (trust-boundary авторизации):
1. **BLOCKING-1** `retrieval.py _require_visible` не сверял `record.tenant_id` с `access.tenant_id`
   (tenant-изоляция делегирована store). **Fix**: добавлена record-boundary провёрка
   tenant + валидность scope + user.
2. **BLOCKING-2** `ConsolidateWorkflow` не авторизовал sources (не требовал tenant-соответствие
   sources≡access≡target, не проверял user-visibility каждого source, target без
   `_validate_creation`). **Fix**: `_validate_same_scope(records, access)` требует tenant
   источника == tenant caller; user-scope требует user_id == access.user_id для каждого;
   `run()` валидирует target_key/base_provenance и `require_accessible(target_key, access)`.

Оба покрыты regression-тестами (+5). Повторный узкий review: **BLOCKING_FINDINGS=0, VERDICT=PASS**.
Non-blocking наблюдение: вызывающий может консолидировать СВОИ user-sources в tenant-скоуп
того же tenant — расширение видимости собственных данных (не чужих принципалов), допустимо.

## 13. Регрессия (фактическая, после полного canonical)

Полный canonical на исправленном коде (`scripts/run_tests.sh`):

```
=== Summary: 3145 files, 33247 tests passed, 102 failed, 285 skipped (100%) in 1068.4s ===
FULL_CANONICAL_EXIT=1   (fail-red)
```

- **Phase 1/2/3 файлы в failures: 0** (`platform_policy/persistence/api/memory`, `agent_runtime`, `agent_orchestration` и их тесты — ни одного).
- **31 failing файл** — все внешние (acp, tools/network, plugins, run_agent providers, operations_v2, hermes_cli, intent_router, hermes_state, live/subprocess guards):
  - **0** с non-empty git diff → фаза их не изменяла;
  - **0** импортирующих phase-модули → нет coupling;
  - → **NEW_REGRESSIONS=0** (тот же pre-existing/ENVIRONMENTAL пул, что в Phase 1/2).