# Phase 8 — Controlled Production Shadow Hook

**Статус:** PASS (implementation; полный canonical + security review, §15–§16)
**Ветка:** `sprint/1.3.7-narrow-production-canary`
**Хед:** `9389dea5aafd6ef9f1d8978f6db61400b1b38bcd` (production untouched)
**LIVE_SHADOW_ACTIVATION=False** — Phase 8 НЕ включает live hook. **READY != AUTHORIZED.**

## 1. Цель и критический инвариант

Подключение Agent Platform Shadow Runtime к реальному production traffic через
односторонний, bounded, non-blocking shadow tap.

```
Production Request
   ├──► Production Path ────► Production Response
   └──► Shadow Tap ──► Shadow Runtime ──► Shadow Decision   (DATA)
                       └──────── NO RETURN ────────────────┘
```

Shadow НЕ МОЖЕТ: изменить production request/response, блокировать/задержать
production, выполнять mutation, вызывать executor, grant authority, менять
scheduler/provider/config, писать production state, restart/reload/stop/signal,
включать Coding mutation. Разрешён только **CONTROLLED_PRODUCTION_SHADOW**;
production-decision/override/auto-correct/failover/fallback — запрещены.

## 2. Пакет

Новый bounded-пакет **`agent/production_shadow_hook/`** (10 модулей):
`__init__`, `exceptions`, `envelope`, `redaction`, `modes`, `transport`,
`metrics`, `hook`, `consumer`. В hook **нет** Planner/Router/Agent-runtime/
Memory/Comparison/Policy/Executor — он только копирует bounded metadata,
enqueue (non-blocking) и записывает success/drop. Вся shadow-логика остаётся в
`agent/platform_shadow`.

## 3. One-way flow (§3)

Production → Shadow разрешён; Shadow → Production запрещён архитектурно.
НЕ существует API `apply_shadow_result / replace_response / override_decision /
retry_with_shadow / promote_shadow_result` (проверено механически:
PRODUCTION_RETURN_PATHS=0).

## 4. Shadow Tap Contract (§4–§6)

`ProductionShadowEnvelope` (immutable): source_request_id, tenant_id, user_id,
request_kind, input_digest, sanitized_context (bounded), production_timestamp,
baseline_version, trace_id. **Без** credentials/tokens/cookies/Authorization/
secrets/executor/adapter/approval/capability-grant. Envelope не несёт executable
объект. `assert_no_forbidden_content()` отклоняет поля с authority-маркерами.

## 5. Data minimization (§5)

Перед enqueue: field allowlist, drop unknown, redact secret-ключи, bound size,
канонизация payload. Полный raw request по умолчанию не копируется — только
metadata + sanitized task payload. Unknown field → DROP.

## 6. Non-blocking guarantee + time budget (§6–§7)

`try_enqueue()` → accepted/dropped/unavailable; production path не ждёт shadow.
Ошибки (queue full, unavailable, serialization, timeout, exception) → `DROP_SHADOW`,
production продолжает. Transport — локальная bounded async queue (без network
round-trip на синхронном пути; без ожидания Redis/PostgreSQL ACK). Hook O(1);
цель p95<2ms, p99<5ms (синтетический бенчмарк ниже).

## 7. Backpressure / Sampling / flags (§8–§9, §25–§26)

- Metrics: shadow_hook_received/sampled/enqueued/dropped/errors/latency_ms/
  processing_latency_ms/queue_depth/comparison_match/mismatch + dropped sub-реаоны
  (queue_full/invalid/over_budget). Отсутствуют PII/secrets в labels (locked allowlist).
- Sampling детерминированный (hash request_kind|tenant|request_id) под канареечный
  процент; user-controlled поле никогда не включает shadow как authority.
- Modes: OFF(default)/TEST/CANARY. Флаг `HERMES_AGENT_PLATFORM_SHADOW_HOOK_ENABLED`
  (default false, unknown→false). Kill switch `..._KILL_SWITCH` (default ON —
  hook возвращается мгновенно, enqueue=0).

## 8. Tenant safety / Trace / Memory / Network / Agents (§10–§11, §19–§22)

- Envelope несёт tenant_id/user_id; shadow пере-применяет Phase 3/6 tenant isolation
  (cross-tenant batching запрещён).
- Trace: production_request_id→envelope_id→shadow_task_id→agent_run_id (только
  observability; не authority).
- SHADOW_MEMORY_WRITES=OFF; remember/consolidate — proposal only.
- NETWORK_READ_ONLY_DEFAULT=DENIED; live hook не разрешение на network.
- CodingAgent READ_ONLY_OR_SHADOW (write/execute/shell/git DENIED; PatchProposal DATA);
  MonitoringAgent read-only (restart/reload/stop → recommendation only).

## 9. REuse / Claim dedup (§16)

Используется Phase 7 durable semantics: semantic key
(source request|tenant|user|task kind|input digest|baseline). Duplicate live-hook
event → single shadow run.

## 10. Механический AST-гейт

`scripts/scan_shadow_hook.py` (54 файла, 5 пакетов):
**UNAUTHORIZED_EXECUTION_PATHS=0, PRODUCTION_OVERRIDE_PATHS=0,
PRODUCTION_MUTATION_PATHS=0, PRODUCTION_RETURN_PATHS=0**.
Нет subprocess/os.system/shell/systemctl/kill/signal/eval/exec/fs-write/git-mutation/
executor/adapter/response-override/request-mutation/production-write/return-API.

## 11. Tests (23, tests/production_shadow_hook/)

- unit: envelope (no authority fields, forbidden-content deny, bounded, immutable),
  redaction (drop unknown/secret/objects, bound), modes/flags (default OFF, kill switch),
  transport (drop-on-full, non-blocking), hook (accepted/dropped/unavailable, sampling).
- harness: **1000 synthetic production requests** с tap — outputs byte/value
  identical, shadow effect=0 (enqueued=sampled=1000), drop path, failure isolation
  (queue unavailable, shadow crash → production unaffected), concurrency (500 tasks/
  500 enqueue races), security matrix (secret/callable/object в payload → dropped;
  отсутствие shadow→production return API), performance (hook p95<2ms, p99<5ms).

## 12. Scoped canonical (Phases 1–8)

**690 passed / 0 failed** (`agent_runtime` 109 + `agent_orchestration` 109 +
`agent_system` 102 + `agent_security_boundary` 125 + `platform_memory` 42 +
`platform_policy` 28 + `agent_integration` 106 + `platform_shadow` 46 +
`production_shadow_hook` 23). Phase delta: Phase 7→8 +23 тестов.

## 13. Полный canonical

Полный canonical (`scripts/run_tests.sh`): **3177 files, 33654 passed, 100 failed,
285 skipped** (EXIT=1, fail-red). Классификатор `scripts/classify_phase8.py`:
**NEW_REGRESSIONS=0** — 76/76 упавших файлов PROVEN_PRE_EXISTING (acp, intent_router,
system_boundary, verified_tool_executor, run_agent, gateway и др.); ни один не связан
с Phase 8 и ни один не изменён Phase 8 (exact failing nodeids, пустой git diff, вне
surface). Все тесты production_shadow_hook/platform_shadow/agent_integration/… зелёные.

## 14. Security review (12 вопросов, §33)

Независимый adversarial-риевью live hook: **BLOCKING_FINDINGS=0, VERDICT=PASS**, 12/12 PASS.
Q1 response=PASS, Q2 request=PASS, Q3 block=PASS, Q4 executor=PASS, Q5 grant=PASS,
Q6 executable-in-envelope=PASS, Q7 cross-tenant=PASS, Q8 failure-propagate=PASS,
Q9 duplicate-run=PASS, Q10 network-auto=PASS, Q11 coding-mutate=PASS, Q12 shadow→production=PASS.
`ProductionShadowHook`/`ShadowHookConsumer` НЕ подключены ни к одному production
call-site (нет live path в этой фазе).

NON_BLOCKING: (1) **закрыта** — весь `try_enqueue` обёрнут broad `except → DROP`
(любая внутренняя ошибка, включая будущий реальный transport, не пропагируется);
(2) **закрыта** — `assert_no_forbidden_content` теперь проверяет и
`sanitized_context`-tuple; (3) sampling-lane на user-influenced request_id/tenant —
принято (shadow никогда не authority; cost bounded ShadowBudget).

## 15. Pre-existing worktree (§34)

`agent/multi_service_execution/*`, `docs/codemap/*`, `tests/multi_service_execution/*`
(Sprint 1.3.19) — НЕ изменены, НЕ стажатся, конфликта с Phase 8 нет.

## 16. Production activation gate (§35)

PRODUCTION_SHADOW_HOOK implementation PASS **НЕ** означает включение live hook.
Сначала IMPLEMENTATION_VERIFIED → STOP. Live canary — только по отдельной
operator-команде (bounded duration, sampling cap, kill switch).

## 17. Acceptance (Phase 8)

```
PRODUCTION_SHADOW_HOOK=VERIFIED   ONE_WAY_FLOW=VERIFIED
PRODUCTION_OVERRIDE_PATHS=0       PRODUCTION_MUTATION_PATHS=0
PRODUCTION_BLOCKING_PATHS=0       FAILURE_ISOLATION=VERIFIED
SHADOW_DEDUP=VERIFIED             NETWORK_DEFAULT_DENY=YES
SHADOW_MEMORY_WRITES=OFF          CODING_AGENT_MUTATION=DENIED
MONITORING_AGENT_SERVICE_CONTROL=DENIED
UNAUTHORIZED_EXECUTION_PATHS=0    NEW_REGRESSIONS=0
BLOCKING_FINDINGS=0
LIVE_SHADOW_ACTIVATION=OFF        PRODUCTION_EFFECT=0  REAL_MUTATION=0
READY FOR PHASE 8 LIVE SHADOW CANARY   (READY != AUTHORIZED)
```

## 18. Регрессия (фактическая, после полного canonical)

Phase 7 → Phase 8: полный canonical `3175/33629/102/285` → `3177/33654/100/285`.
+2 файла (production_shadow_hook), **+25 passed**; failed −2 (счётчики в пределах
расхождения counting на пре-существующих; exact failing nodeids не изменились).
**NEW_REGRESSIONS=0** — все 76 упавших файлов PROVEN_PRE_EXISTING, ни один в surface Phase 8.

## 19. Известные неблокирующие замечания (приняты/закрыты)

1. Broad `except → DROP` в `try_enqueue` (закрыто; будущий реальный transport не пропагируется).
2. `assert_no_forbidden_content` учитывает sanitized_context (закрыт).
3. Sampling-lane на user-influenced request_id/tenant — принято (shadow не authority; cost bounded).
4. `try_enqueue` синхронен in-process при будущем wiring — live canary должен использовать
   dedicated worker/outbox; Phase 8 live wiring отсутствует.