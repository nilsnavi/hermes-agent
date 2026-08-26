# Agent Orchestration Framework Hermes 2.0 — Phase 1
## Platform Foundation (Control Plane foundation layer)

> **Статус:** реализовано (Phase 1 scope). Дата: 2026-08-25
> Репозиторий: `~/.hermes/hermes-agent-sprint137` · ветка `sprint/1.3.7-narrow-production-canary`
> Head: `9389dea5…` (не менялся) · Pre-change backup: `~/hermes-backup-sprint-1.4-phase1-platform-foundation-20260825-212209` (956/956 OK)

---

## 0. Scope Phase 1 (реализовано)

| # | Scope item | Пакет | Статус |
|---|---|---|---|
| 1 | PostgreSQL authority schema, migrations, tenant/user isolation, audit append-only | `agent/platform_persistence/` | ✅ новый |
| 2 | policy contracts, permission models, capability requests, deny-by-default | `agent/platform_policy/` | ✅ новый |
| 3 | BaseAgent contracts, AgentContext, AgentDefinition, lifecycle state machine | `agent/agent_runtime/` | ✅ дельта: добавлен `lifecycle.py` |
| 4 | Task, TaskStep, DAG, Supervisor contracts | `agent/agent_orchestration/` | ✅ дельта: добавлен `supervisor.py` |
| 5 | API request/response schemas, auth boundaries, versioning | `agent/platform_api/` | ✅ новый |

Существующие (из прошлой сессии) `agent/agent_runtime/{base,models,permissions,quality,registry}` и
`agent/agent_orchestration/{models,states,task_graph}` — верифицированы как зелёные (137 тестов) и
использованы как база; не переписывались.

---

## 1. platform_persistence (item 1)

- **isolation.py** — `TenantRef` + `Owner`. Каждый record принадлежит ровно одному tenant
  (и, при user-scope, одному user). `can_access`/`require_access`/`ensure_same_tenant`
  enforce пересечение на уровне модели; cross-tenant/cross-user → `TenantIsolationViolation`.
  Semantics: tenant-scoped target читается любым актором в tenant; user-scoped target —
  только этим user-ом или tenant-scoped (system) актором. Строго без wildcard.
- **migrations.py** — `Migration` (version/name/up/down/irreversible), `MigrationRegistry`,
  `migrate_up`/`migrate_down`. Каждая миграция обязана иметь `down` (иначе
  `MigrationNotReversible`); `rollback_plan` исключает down миграции, недостижимые для
  отката. Engine pure/stdlib-only, SQL-исполнение делегировано `SchemaExecutor`.
- **pg_schema.py** — `SCHEMA_MIGRATIONS` (version 1, 2). Каждая authority-таблица несёт
  `tenant_id`; `version` для optimistic concurrency; FK `RESTRICT`. Миграция 2 добавляет
  append-only триггеры (`BEFORE UPDATE/DELETE ON audit_events` → raise exception).
- **audit.py** — `AuditRecord` (immutable) + `AuditLog` (append-only; `append`/`get`/`snapshot`
  только; нет update/delete/remove; sequence контракт).

## 2. platform_policy (item 2)

- **permissions.py** — `CANONICAL_PERMISSIONS` (строгий словарь), `PlatformScope`,
  `PermissionGrant` (immutable, copy-out безопасный), `intersect`. Неизвестное permission
  имя → `InvalidPermission` при конструировании (fail-closed).
- **policy.py** — `DenyByDefaultPolicy` (stateless): `evaluate`/`require`/`permitted_permissions`.
  Отсутствие явного grant = DENIED. Никакого default grant, auto-approval, caller-supplied verdict.
- **capability.py** — `CapabilityRequest`/`CapabilityRequestSet`, `CANONICAL_CAPABILITIES`,
  `CAPABILITY_TO_PERMISSION`. Не-канонический target (message_exchange → message.write)
  не-грантируем по конструкции → всегда deny.

## 3. agent_runtime lifecycle (item 3)

- **lifecycle.py** — `AgentLifecycleStatus` (REGISTERED→READY→ACTIVE/DISABLED/RETIRED),
  `AgentLifecycleTransition`, `AgentLifecycle`. Fail-closed: illegal transition → `AgentContractError`;
  RETIRED/DISABLED терминальны и иммутабельны; disabled→active через direct transition невозможен
  (нет flapping). Lifecycle не имеет execute/run/authorize поверхности.

## 4. agent_orchestration supervisor (item 4)

- **supervisor.py** — `OutcomeKind`, `OutcomeDisposition`, `AttemptContext`, `SupervisorPolicy`.
  Fail-closed classifier: UNKNOWN/TIMEOUT/side-effect-evidence → HUMAN_REVIEW (никогда не auto-retry);
  FAILED в бюджете → RETRY_SAFE; исчерпан + alternative → ALTERNATIVE; иначе ESCALATE; SUCCESS → NONE.
  Supervisor НЕ выполняет и НЕ даёт authority — только disposition.
- `EscalationEvent` — typed escalation sink.

## 5. platform_api (item 5)

- **versioning.py** — `ApiVersion`, `parse_request_version` (supported-only, fail-closed).
- **auth.py** — `Principal` (tenant/principal/user/scopes, обязательный tenant),
  `authenticate_bearer`, `enforce_tenant_boundary`. Scope берётся из principal, НЕ из body;
  mismatch body-tenant vs principal-tenant → denied.
- **schemas.py** — typed request/response контракты (Agents/Task/Memory), idempotency-key
  обязателен для mutating endpoints.

---

## 6. Архитектурная граница (подтверждена)

Все 5 пакетов — **pure contracts / stdlib-only**, без импорта execution kernel. Механическая
проверка (AST карта всех .py):
- импортов `subprocess/os.system/Popen/VerifiedToolExecutor/RuntimeOrchestrator/systemctl/execution/runtime/orchestrator/recovery/sandbox/capability_router` — **0**;
- вызовов tool-execution — **0** (единственные `execute` в migrations.py — `SchemaExecutor.execute(sql)`, duck-typed Protocol, это миграционный контракт, не tool);
- **второй execution engine отсутствует; domain layer не импортирует execution adapters; platform layer не получает execution authority.**

---

## 7. Verification

- `compileall` по всем 5 пакетам + тестам: **OK**.
- Scoped canonical (`scripts/run_tests.sh`): **242 passed / 0 failed** (16 файлов) =
  agent_runtime 109 + agent_orchestration 53 + platform_policy 28 + platform_persistence 30 + platform_api 22.
- Production untouched: Gateway `MainPID=171817 / NRestarts=0 / active` (не менялся); execution kernel modified = NONE; `git diff --cached` пуст; HEAD не менялся; новые файлы — untracked.
- Полный canonical: см. секцию "Регрессия".

## 8. Acceptance gates Phase 1

| Gate | Статус |
|---|---|
| второй execution engine отсутствует | ✅ (AST scan, 0 импортов) |
| domain layer не импортирует execution adapters | ✅ (0 coupling) |
| platform layer не получает execution authority | ✅ (нет execute/authorize/grant surface) |
| все state machines покрыты unit tests | ✅ (Task, TaskPlan, TaskGraph, Task lifecycle, Agent lifecycle, Supervisor) |
| migration reversible | ✅ (каждый Migration имеет down; тесты rollback) |
| tenant isolation verified | ✅ (isolation.py + DB-boundary tenant_id на всех таблицах) |
| audit immutable | ✅ (AuditLog append-only + триггеры в схеме; тесты) |
| security review | ✅ (независимый adversarial review: BLOCKING=0, VERDICT=PASS) |

## 9. Регрессия (фактическая, после полного canonical)

Полный canonical (`scripts/run_tests.sh`):

```
=== Summary: 3133 files, 33153 tests passed, 101 failed, 285 skipped (100%) in 1055.5s ===
TEST_RUNNER_EXIT_CODE=1   (fail-red)
```

- **Phase-1 файлы в failures: 0.** Ни один из `platform_policy/platform_persistence/platform_api/agent_runtime/agent_orchestration` и их тестов не упал.
- **33 failing файла** — все внешние (acp, tools/network, plugins/memory+video+image, run_agent provider-routing, operations_v2, gateway turn_lease/wecom, intent_router calibration_safety, hermes_state, live_system_guard/subprocess_stdin_guard): 
  - **0** с non-empty git diff (`git diff --stat HEAD` пуст) → фаза их не изменяла;
  - **0** импортирующих phase-1 модули (`platform_policy/persistence/api`, `agent_runtime`, `agent_orchestration`) → нет coupling;
  - → **NEW_REGRESSIONS=0** (pre-existing/ENVIRONMENTAL сетевые/провайдерные/плагинные failures, не связаны с Phase 1).

## 10. Security review

Независимый adversarial read-only review (субагент): **BLOCKING_FINDINGS=0, VERDICT=PASS**.
Проверены все 9 acceptance-пунктов: обход deny-by-default, cross-tenant, audit mutation,
reversibility migrations, не-канонический permission (message.write никогда не грантируется),
lifecycle fail-closed/no flapping, supervisor no-blind-recovery (UNKNOWN/TIMEOUT/side-effect →
HUMAN_REVIEW), API tenant-from-principal, отсутствие authority-поверхности и импортов kernel.