# Phase 7 — Shadow Runtime & Observability

**Статус:** PASS (после полного canonical + security review, §9–§10)
**Ветка:** `sprint/1.3.7-narrow-production-canary`
**Хед:** `9389dea5aafd6ef9f1d8978f6db61400b1b38bcd` (production untouched)

## 1. Цель и модель

Запуск новой Hermes Agent Platform в **shadow-режиме** параллельно с production
runtime: shadow принимает копию реальных входящих задач, строит TaskPlan, выполняет
routing, собирает Memory Context (read-only), запускает read-only system agents,
выдаёт AgentObservation, считает Supervisor disposition, собирает audit/metrics/
traces — но **НЕ влияет** на production: не изменяет решения/response, не выполняет
mutations, не вызывает tools с side effects, не трогает scheduler/provider/config/
gateway, не пишет production files, не активирует Coding mutation, не становится
authority.

```
Production Request → [Production Runtime] → Production Result
                          │
                          ▼  (копии задач)
                 Shadow Agent Platform → Shadow Decision/Observation  (DATA)
                          └──────────── NO JOIN, NO OVERRIDE ─────────────┘
```

**Запрещено:** `shadow_result → production_override | capability_grant |
execution_authority | mutation`.
**P0 invariant:** `SHADOW_CANNOT_AFFECT_PRODUCTION=True`.

## 2. Пакет

Новый bounded-пакет **`agent/platform_shadow/`** (11 модулей):
`__init__`, `exceptions`, `models`, `sampling`, `audit`, `observability`,
`comparison`, `guards`, `claim_store`, `dispatcher`, `runtime`.
Второй execution engine НЕ создан — shadow переиспользует Phase 6 read-only
вертикаль (`agent_integration`), единственная read-site — `ReadOnlyProvider`
после ADMIT + grant.

## 3. Shadow Envelope (immutable DATA)

`ShadowTaskEnvelope`: shadow_id, source_request_id, tenant_id, user_id, task_kind,
input_digest, received_at, sampling_reason, production_context_digest,
baseline_version. **Без** credentials/secrets/execution-token/approval-token/
adapter/executor. Валидация обязательных полей.

## 4. Shadow Decision (DATA ONLY)

`ShadowDecision`: task_id, plan_digest, selected_agent, agent_observation,
supervisor_disposition, confidence, policy_disposition, boundary_disposition,
memory_digest, duration, comparison_class, audit_id. Без authority. Метод
`never_authority()` возвращает True; поля override/grant/execute отсутствуют.

## 5. Proизводственная изоляция (P0)

Механически доказуемо (`scripts/scan_shadow_runtime.py`): shadow-пакет не может
return/mutate production response, вызывать production executor, писать
production state, grant capabilities, менять scheduler/provider/gateway.
`PRODUCTION_OVERRIDE_PATHS=0`; любой production-side callable в shadow →
`IsolationGuard.reject_production_side` → DENY/absent.

## 6. Sampling (§6)

`ShadowSamplingMode` OFF (default) / SAMPLE / FULL_SHADOW. При `sample` — толь
kеш-ключ boundary (tenant|task_kind|request_hash), детерминированный; caller/
tenant-булев `shadow=true` **никогда не authority**. `sample_rate_per_mille` в [0,1000].

## 7. Read-only agents (§7)

Research/Planner/Reviewer/Monitoring/Memory/Coding(READ_ONLY_OR_SHADOW). Все:
write_files=DENIED, execute_code=DENIED, service_control=DENIED. Monitoring —
только read-only status; CodingAgent PatchProposal — DATA ONLY.

## 8. Закрытые долги Phase 6

- **ORCH-003 (§8):** `SupervisorOrchestrationFlow.run` теперь **внутренне** исключает
  `failed_agent_id` из alternative routing (candidates = alternatives − failed;
  failed-единственный → ESCALATE, без blind re-dispatch). Caller-пред-прунинг больше
  не требуется.
- **Deterministic read-only gate (§9):** `build_read_only_gate` — НЕТ allow-all stubs.
  Только capability из closed enum `ReadOnlyCapability` с side_effect READ_ONLY;
  unknown capability / unknown side-effect / NETWORK → DENY (policy+router+boundary
  сходятся).
- **Durable idempotency (§10):** `ShadowClaimStore` Protocol + `InMemoryClaimStore`
  (semantic key, claim-first, single winner, terminal replay, fail-closed unknown
  → runtime не запускает duplicate и не считает запущенным). PostgreSQL backend —
  Protocol-only (stdlib, без импорта БД).

## 9. Observability / Tracing / Audit (§11–§13)

- `ShadowMetrics`: 16 фиксированных имён; labels — только закрытый allowlist значений
  (agent_id={6 roles}, mode, class), никаких пользовательских текстов/секретов/
  email/токенов/полных промптов. Cardinality bounded.
- `ShadowTracer`: correlation-id chain, не authority.
- `ShadowAuditStore`: append-only bounded, 12 событий в порядке §13
  (SHADOW_RECEIVED…SHADOW_COMPLETED); событие не replay-аблем как исполнение.

## 10. Сравнение (§14–§15)

`ComparisonEngine` → ComparisonClass (MATCH/PARTIAL_MATCH/DIFFERENT_AGENT/
DIFFERENT_PLAN/DIFFERENT_DISPOSITION/SHADOW_DENIED/SHADOW_UNKNOWN/NOT_COMPARABLE).
Mismatch — метрика/аудит только. **Нет автокоррекции**: нельзя заменить production
результат, нельзя при падении production исполнять shadow.

## 11. Изоляция сбоев и backpressure (§18–§21)

- Любая shadow-ошибка/timeout/memory-fail/route-fail → record only; production не
  блокируется (oververz `except Exception` в runtime диспатче).
- `ShadowBudget`: max concurrency + acquire-timeout → перегруз → SKIP/DROP
  (`ShadowOverloaded`), не блокирует production.
- `TimeBudget`: bounded per-task время (`ShadowTimeout`).
- Supervisor depth / DAG bounded; нет безграничных retry/recursive задач.

## 12. Backpressure-тесты + concurrency + security-matrix

`tests/platform_shadow/`: 46 тестов. Scenarios A–J (§26), concurrency
(100 tasks / 100 duplicates / 100 claim-races / 50 tenant mixes; duplicate=0,
cross-tenant-leak=0, deadlock=0, production effect=0), security-matrix (§23:
forged/fake result, cross-tenant, registry drift, memory injection, unknown
capability, monitoring no-service-mutation, shadow→production override, shadow
audit replay) — production effect=0 во всех.

## 13. Scoped canonical (Phases 1–7, фактическое)

**667 passed / 0 failed** (`agent_runtime` 109 + `agent_orchestration` 109 +
`agent_system` 102 + `agent_security_boundary` 125 + `platform_memory` 42 +
`platform_policy` 28 + `agent_integration` 106 + `platform_shadow` 46).
Phase delta: Phase 6→7 +49 тестов.

## 14. Механический AST-гейт

`scripts/scan_shadow_runtime.py` (45 файлов, 4 пакета):
**UNAUTHORIZED_EXECUTION_PATHS=0** (F1=0,F2=0,F3=0) и **PRODUCTION_OVERRIDE_PATHS=0**.
Нет subprocess/os.system/shell/systemctl/kill/signal/eval/exec/fs-write/git-mutation/
direct executor/override-поверхности.

## 15. Полный canonical

Phase 7 scoped canonical (Phases 1–7): **667 passed / 0 failed**.

Полный canonical: **3175 files, 33629 passed, 102 failed, 285 skipped** (EXIT=1, fail-red).
Классификатор `scripts/classify_phase7.py`: **NEW_REGRESSIONS=0** — 77/77 упавших файлов
PROVEN_PRE_EXISTING; ни один не связан с Phase 7 и ни один не изменён Phase 7 (exact
failing nodeids, пустой git diff, вне surface). Все тесты platform_shadow/agent_integration/
agent_orchestration/agent_system зелёные во full canonical.

## 16. Security review (12 вопросов, §31)

Независимый adversarial-риевью shadow runtime: **BLOCKING_FINDINGS=0, VERDICT=PASS**, 12/12 PASS.
Q1 production-result=PASS, Q2 executor/second-engine=PASS, Q3 grant=PASS,
Q4 authority-in-envelope=PASS, Q5 memory-write=PASS, Q6 coding-write=PASS,
Q7 service-mutation=PASS, Q8 network-deny=PASS, Q9 failure-block=PASS,
Q10 duplicate-run=PASS, Q11 cross-tenant-leak=PASS, Q12 second-engine=PASS.
Единственная read-site — `_provider.read` post-admission; `IsolationGuard` отклоняет
чужие callable; shadow output — инертная DATA; нет live-wiring (production activation OFF).

NON_BLOCKING (закрыты/приняты): (3) — **закрыта**: `dispatch` теперь перехватывает любую
shadow-внутреннюю ошибку (в т.ч. полный audit store / claim-bаg) → fail-record, не
пропагируется в production; (1) shared-store coupling при wiring — принят (Phase 7 без
live-wiring; при подключении — dedicated stores + budget против общего store); (2)
private-attr coupling `vertical._router` — принят, технический долг (явный routing-метод).

## 17. Pre-existing worktree state (§33)

`agent/multi_service_execution/*`, `docs/codemap/*`, `tests/multi_service_execution/*`
(Sprint 1.3.19) — НЕ изменялись, НЕ стажируются, НЕ включаются в Phase 7.
Конфликт: Phase 7 не пересекается с этими путями → нет конфликта.

## 18. Production / commit (§32, §34)

Не подключать shadow к live gateway; no production hook; gateway before/after
MainPID/NRestarts/ActiveState unchanged. Commit/tag/push не выполняются. Phase 1–7
остаются uncommitted control-plane artifacts до baseline consolidation.

## 19. Acceptance (Phase 7)

```
SHADOW_RUNTIME=VERIFIED                     PRODUCTION_OVERRIDE_PATHS=0
PRODUCTION_EFFECT=0                         SECOND_EXECUTION_ENGINE=FALSE
READ_ONLY_AGENT_VERTICAL=VERIFIED           AGENT_REGISTRY_RUNTIME_OWNED=YES
MESSAGE_BUS_ATOMIC=YES                      DURABLE_SHADOW_IDEMPOTENCY=VERIFIED
NETWORK_READ_ONLY_DEFAULT=DENIED            SHADOW_MEMORY_WRITES=OFF
CODING_AGENT_WRITE_FILES=DENIED             CODING_AGENT_EXECUTE_CODE=DENIED
MONITORING_AGENT_SERVICE_CONTROL=DENIED     CROSS_TENANT_ISOLATION=VERIFIED
UNAUTHORIZED_EXECUTION_PATHS=0              NEW_REGRESSIONS=0
BLOCKING_FINDINGS=0
```

**STOP** после PASS.

## 20. Регрессия (фактическая, после полного canonical)

Phase 6 → Phase 7: полный canonical `3170/33582/100/285` → `3175/33629/102/285`.
+5 файлов (platform_shadow 10 модулей + 1 оркестр-тест), **+47 passed**; failed счётчик
+2 — все 77 упавших файлов PROVEN_PRE_EXISTING (acp, intent_router, system_boundary,
verified_tool_executor, run_agent, gateway и др.; ни одного в surface Phase 7).
**NEW_REGRESSIONS=0.**

## 21. Известные неблокирующие замечания (принятый техдолг)

1. Shared-store coupling при будущем live-wiring (dedicated stores + budget).
2. Private-attr coupling `vertical._router` в shadow runtime (явный routing-метод).
   (Оба — вне архитектурных границ; Phase 7 производственную активацию не выполняет.)