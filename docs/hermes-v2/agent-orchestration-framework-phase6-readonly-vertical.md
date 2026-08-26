# Phase 6 — First Read-Only System Agents Integration (vertical)

**Статус:** PASS (после полного canonical + security review, см. §11–§12)
**Ветка:** `sprint/1.3.7-narrow-production-canary`
**Хед:** `9389dea5aafd6ef9f1d8978f6db61400b1b38bcd` (production untouched)

## 1. Цель

Собран первый end-to-end вертикальный контур Agent Platform — **control-plane,
только read-only**:

```
Task/TaskStep + principal
  → TaskPlan/Planner (data)
  → ReadOnlyRouter (runtime-owned sealed registry, enabled, admissible, capability-matched)
  → AgentRun isolation (tenant/user/task/step/agent/generation + digests, idempotency)
  → AgentContext (Memory gateway Top-K, redacted/sanitized)
  → NetworkReadOnlyPolicy (remote/network default DENIED)
  → AgentCapabilityIntent → PlatformPolicy → SecurityBoundaryGate
  → READ_ONLY disposition
  → ReadOnlyProvider seam (единственная read-site; только после ADMIT + runtime grant)
  → AgentObservation
  → Supervisor state disposition
  → bounded audit event (append-only, DATA)
```

Второй execution engine НЕ создан: единственный site чтения — узкий внедряемый
`ReadOnlyProvider`, достижимый только после ADMIT + авторизации гранта. CodingAgent ≡
`READ_ONLY_OR_SHADOW`.

## 2. Реализованные модули

Новый пакет **`agent/agent_integration/`** (14 файлов):
- `capabilities.py` — typed allowlist `ReadOnlyCapability` (8 токенов,
  НОЛЬ `READ_ANYTHING`), access-class (LOCAL/REMOTE/NETWORK).
- `network_policy.py` — `NETWORK_READ_ONLY_DEFAULT_DENIED=True`; remote/network не
  авт-разрешаются (только явный certified interface).
- `gate_token.py` — runtime-owned **opaque grant** (`OpaqueGrant`/`RuntimeGrantSeal`):
  токен без экспортируемого значения; import/copy/same-value/foreign/stale → DENY.
- `audit_store.py` — `PersistentAuditStore` Protocol + `InMemoryAuditStore`
  (детерминированный, append-only, bounded: полный → `AuditStoreFull`, без drop).
- `agent_run.py` — `AgentRun` биндинг + семант. idempotency key + атомарный
  `claim()` (duplicate execution=0 в гонке) + `RunIsolationError` (cross-tenant DENY).
- `context.py` — `AgentContextAssembler`: только через gateway Top-K (никогда
  «вся память»), повторная redaction + injection-drop. Context — data, не authority.
- `result.py` — `AgentObservation` (no execute/approved/grant authority-полей).
- `supervisor_state.py` — `AgentRunState` machine (READY/RUNNING/WAITING/COMPLETED/
  FAILED/UNKNOWN/HUMAN_REVIEW), `bounded_retry_decision` (retry только read-only+
  idempotent, в бюджете), `exclude_failed` (ORCH-003).
- `readonly_routing.py` — `ReadOnlyRouter` по sealed registry + enabled + ADMISSIBLE
  (unknown-Health EXCLUDE) + capability-matched; не execute/grant.
- `agents.py` — MVP data-producers: Research, Planner, Reviewer, Monitoring, Memory,
  Coding shadow; `PatchProposal` (DATA ONLY, write_requested никогда не пишет).
- `vertical.py` — `ReadOnlyAgentVertical` + `build_read_only_gate`.
- `error_taxonomy.py`, `metrics.py` — typed outcomes (§25) + fixed metrics (§31).

Расширение control-plane реестра: роль **MONITORING** (SystemAgentRole) — агенты: 6.

Харденинги существующих модулей:
- `agent_orchestration/message_bus.py` — атомарный `consume_effective/consume_atomic`
  (lock→inspect→pop→mark) — закрывает **ORCH-002** (§21).
- `agent_orchestration/messages.py` — каноническая сериализация payload —
  str/int/finite-float/bool/None/bounded-контейнеры; запрет callables/objects/
  executors/adapters/authority — закрывает **ORCH-001** (§22).
- `agent_system/definitions.py`, `capabilities.py` — +`MONITORING_OBSERVATION`.
- ORCH-003 (§23): failed-агент автоматически в exclude-set при reroute.

## 3. Read-only capability set (typed, bounded)

`READ_ONLY_ALLOWLIST` (ровно 8): READ_FILE_METADATA, READ_TEXT_RESOURCE, SEARCH_INDEX,
READ_STATUS, READ_HEALTH, READ_CONFIGURATION_SUMMARY, READ_AUDIT_SUMMARY,
READ_MEMORY_CONTEXT. Generic `READ_ANYTHING` отсутствует (enum закрыт).
`side_effect_for(cap)=READ_ONLY`; все MVP-токены `LOCAL_READ_ONLY`.

## 4. DECLARATION != GRANT

`READONLY_AGENT_CAPABILITIES` — описательная карта (метаданные). Вертикаль проверяет,
что агент декларирует capability (declaration-gate), НО финальная READ-адмиссия —
только SecurityBoundary (mandatory path). Caller-заявленный side-effect/verdict — data,
не authority (см. Phase 5).

## 5. Runtime-owned registry binding (закрыт Phase 5 risk #1)

`ReadOnlyAgentVertical` принимает `SealedRegistry` (SystemAgentRuntime): перед запуском
`assert_registry_sealed()` → дрейф ⇒ `REGISTRY_DRIFT` (fail-closed). Router выбирает
только из `registry().list()` (runtime-owned). Произвольный caller-supplied registry
не принимается: роли/impl-id фиксированы в definitions (6 id).

## 6. Audit hardening (закрыт Phase 5 risk #2)

`ExecutionAuditEvent` (immutable, validate): task_id, task_step_id, agent_run_id,
agent_id, tenant_id, user_id, route_decision, memory_context_digest, capability_intent,
policy_decision, boundary_disposition, execution_observation, supervisor_disposition,
provenance, timestamps, sequence. Append-only, bounded. **Audit DATA only, не authority**.
PostgreSQL backend не активируется — Protocol + deterministic test backend готовы.

## 7. Gate-token hardening (закрыт Phase 5 risk #3)

Токен не импортируем, не экспортируем, не replay-аблем: `_secret` per-instance в
`__slots__`; `authorize` сравнение по identity nonce + generation + digest.
Adversarial-тесты: import (нет module-global), copy (deepcopy→DENY), same-value
(чужой nonce→DENY), foreign (другой рантайм→DENY), stale (rotate→DENY) — все DENY.

## 8. Network read-only policy (закрыт Phase 5 risk #4)

LOCAL_READ_ONLY / REMOTE_READ_ONLY / NETWORK_OBSERVATION разделены;
`NETWORK_READ_ONLY_DEFAULT_DENIED=True`. MVP-агенты используют только локальные/
synthetic read-interfaces; никакой auto-allow remote/network.

## 9. Прочее (по всем разделам §)

- AgentContext: без credentials/secrets/adapter/executor/authority (проверяется).
- Supervisor: UNKNOWN→HUMAN_REVIEW; TIMEOUT→bounded retry только read-only+idempotent;
  mutation-like→no retry.
- Router: не execute/dispatch/grant.
- Run isolation: cross-tenant reuse → DENY (metric cross_tenant_denials).
- Идемпотентность: duplicate → не запускает второй work item (claim атомарно).
- Error taxonomy: 10 typed outcomes (§25), без generic bool.
- Metrics: 12 fixed counters, без секретов в labels.

## 10. Тесты и гейты (реальные прогоны)

- Scoped canonical Phases 1–6: **618 passed / 0 failed**
  (agent_runtime 109, agent_orchestration 106, agent_system 102,
  agent_security_boundary 125, platform_memory 42, platform_policy 28,
  agent_integration 106).
- Новый `agent_integration`: **106 тестов** (Scenarios A–F, concurrency 50/100/100/100,
  security-matrix).
- Механический AST-гейт `scripts/scan_readonly_vertical.py` (31 файл):
  **UNAUTHORIZED_EXECUTION_PATHS=0** (F1/F2/F3=0) — нет subprocess/os.system/
  shell/systemctl/kill/signal/eval/exec/fs-write/git-mutation.
- Сообщение: ORCH-001/002/003 закрыты (см. tests/agent_integration/test_message_hardening.py,
  test_agent_run.py, supervisor_state).

## 11. Полный canonical

Phase 6 scoped canonical (Phases 1–6, зелёные control-plane пакеты):
**618 passed / 0 failed** (`agent_runtime` 109, `agent_orchestration` 106,
`agent_system` 102, `agent_security_boundary` 125, `platform_memory` 42,
`platform_policy` 28, `agent_integration` 106).

Полный canonical (`scripts/run_tests.sh`): **3170 files, 33582 passed, 100 failed,
285 skipped** (EXIT=1, fail-red как ожидалось). Классификатор
`scripts/classify_phase6.py`: **NEW_REGRESSIONS=0** — 76/76 упавших файлов
PROVEN_PRE_EXISTING (acp, intent_router, system_boundary, verified_tool_executor,
run_agent, gateway и др.); ни один не связан с Phase 6 и ни один не изменён
Phase 6 (exact failing nodeids). Все тесты `agent_integration`/`agent_system`/
`agent_orchestration` зелёные во full canonical.

## 12. Независимый security review (12 вопросов, §34)

Независимый adversarial-риевью вертикали Phase 6: **BLOCKING_FINDINGS=0, VERDICT=PASS**, 12/12 PASS.

Q1 agent-execution-authority=PASS, Q2 payload-authority=PASS, Q3 memory-grant=PASS,
Q4 registry-caller-controlled=PASS, Q5 coding-write=PASS, Q6 monitoring-restart=PASS,
Q7 reviewer-approve=PASS, Q8 network-readonly-policy=PASS, Q9 failed-self-reroute=PASS,
Q10 cross-tenant-context=PASS, Q11 direct-adapter/executor=PASS, Q12 second-engine=PASS.
Единственная read-site `_provider.read` встречается ровно один раз (vertical), после
`seal.guard` + `decision.allowed`. Никаких subprocess/systemctl/eval/exec/fs-write в
control plane (подтверждено независимо, UNAUTHORIZED_EXECUTION_PATHS=0).

NON_BLOCKING (принято, технический долг, docs §14): (1) generic
`SupervisorOrchestrationFlow` полагается на caller-пред-обрезанный alternative-set —
Phase-6 вертикаль самопрунится (`route_with_failed_exclusion`); (2) `build_read_only_gate`
сеам-заглушки allow-all — реальные границы от closed enum + network policy; (3)
`AgentRunRegistry` claim/idempotency process-local (restart сбрасывает) — в MVP без
authority-влияния, дублирование требует durable-бэкенда.

## 13. Production (не меняется)

`HEAD=9389dea5aa`, staged=0, Phase 6 изменил 0 tracked-файлов (всё — новые
untracked control-plane файлы). Gateway service не трогался/не рестартовался
(локальный sprint-host unit: hermes-dashboard/omniroute; gateway MainPID на WebUI-хосте).
Backup: `~/hermes-backup-sprint-1.4-phase6-readonly-vertical-20260826-133255` (961/961 OK).

## 14. Acceptance (Phase 6)

```
FIRST_READ_ONLY_AGENT_VERTICAL=VERIFIED      SYSTEM_AGENTS_CONTROL_PLANE_ONLY=YES
AGENT_REGISTRY_RUNTIME_OWNED=YES             MESSAGE_BUS_ATOMIC=YES
MESSAGE_PAYLOAD_CANONICAL=YES                MEMORY_IS_NOT_AUTHORITY=VERIFIED
AGENT_MESSAGE_IS_NOT_AUTHORITY=VERIFIED      DECLARED_CAPABILITY_IS_NOT_GRANT=VERIFIED
CODING_AGENT_WRITE_FILES=DENIED              CODING_AGENT_EXECUTE_CODE=DENIED
MONITORING_AGENT_SERVICE_CONTROL=DENIED      NETWORK_READ_ONLY_DEFAULT=DENIED
CROSS_TENANT_ISOLATION=VERIFIED              UNAUTHORIZED_EXECUTION_PATHS=0
NEW_REGRESSIONS=0                            BLOCKING_FINDINGS=0
```

**STOP** после PASS: без commit/tag/push, без mutation-capable агентов, без
production-активации, Phase 7 — только по отдельной команде.