# Agent Orchestration Framework Hermes 2.0 — Phase 4
## Agent System Runtime & First System Agents

> **Статус:** реализовано. Дата: 2026-08-26
> Репозиторий: `~/.hermes/hermes-agent-sprint137` · ветка `sprint/1.3.7-narrow-production-canary`
> Head: `9389dea5aafd6ef9f1d8978f6db61400b1b38bcd` (не менялся) · Pre-change backup: `~/hermes-backup-sprint-1.4-phase4-agent-system-runtime-20260826-092525` (960/960 OK)

---

## 0. Scope Phase 4 (реализовано)

Новый изолированный пакет `agent/agent_system/` — слой **System Agent Runtime** поверх
контрактов `agent/agent_runtime` (Phase 1) и интеграция координации Phase 2
(`agent/agent_orchestration`). Ни один существующий module не переписан.

| # | Scope item | Модуль | Статус |
|---|---|---|---|
| 1 | Agent Registry | `runtime.py` (`SystemAgentRuntime.register/registry`) — переиспользует `agent_runtime.AgentRegistry` | ✅ |
| 2 | System Agent definitions | `definitions.py` (5 MVP: planner/research/coding/reviewer/memory) | ✅ новый |
| 3 | Agent lifecycle runtime | `runtime.py` (`transition`/`lifecycle` на `AgentLifecycle`) | ✅ |
| 4 | Agent context assembly | `context.py` (`ContextAssembler`, `ContextSpec`) — переиспользует `AgentExecutionContext` | ✅ |
| 5 | Agent health/status model | `health.py` (`AgentHealthModel`/`AgentHealthStatus`, fail-closed) | ✅ |
| 6 | Agent capability declaration (descriptive only) | `capabilities.py` (`CapabilitySurface`/`CapabilityDeclaration`) | ✅ |
| 7 | Agent coordination integration | `coordination.py` (`SystemAgentCoordination` → AgentRouter/CoordinationState/MessageBus) | ✅ |

Все модули — pure contracts / stdlib-only (+ sibling control-plane контракты), без
импорта execution kernel, без authority-поверхностей.

---

## 1. Scope item 1+3 — Agent Registry + lifecycle runtime (`runtime.py`)

- `SystemAgentRuntime` — единственный control-plane рантайм: регистрирует system-агентов,
  гоняет их `AgentLifecycle`, агрегирует health.
- **Registry не расширяет production capabilities**: `AgentRegistry` создаётся с
  allowlist ровно из `SYSTEM_IMPLEMENTATION_IDS` (5 фиксированных регекс-идентификаторов).
  Регистрация определения с любым другим `implementation_id` → `AgentContractError`
  (тест `test_registration_does_not_expand_capabilities`). Регистрация — бухгалтерия,
  не permission.
- Lifecycle fail-closed: illegal transition → `AgentContractError`; RETIRED/DISABLED
  терминальны и иммутабельны; self-transition идемпотентен (no-op).

## 2. Scope item 2 — System Agent definitions (`definitions.py`)

- Пять MVP system-агентов как **декларативные** `AgentDefinition` (данные, не процесс).
  Нет analyze/execute/validate-реализаций, нет Python import path.
- **CodingAgent: `write_files=False`, `execute_code=False`** — мутация выключена в этой
  фазе (требуется отдельный composition-gate verified-executor + sandbox). MemoryAgent —
  только `memory_proposal` (`memory_write=False`).
- `SYSTEM_IMPLEMENTATION_IDS = {planner-agent, research-agent, coding-agent, reviewer-agent, memory-agent}`.

## 3. Scope item 4 — Agent context assembly (`context.py`)

- `ContextAssembler` строит один immutable `AgentExecutionContext` (модель переиспользована
  из `agent_runtime.models` — не дублирована).
- Fail-closed: `approved_capabilities` обязаны быть строгим подмножеством `declared`
  capability-поверхности агента; не-задекларированная capability в контексте →
  `ContextAssemblyError`. `agent_id` при задании обязан совпадать с владельцем поверхности.
- Контекст — DATA: модель `AgentExecutionContext` не несёт executor/адаптера/credentials.

## 4. Scope item 5 — Health/status model (`health.py`)

Fail-closed семантика `AgentHealthModel.evaluate` (по порядку):
1. агент не зарегистрирован → `UNKNOWN` (raise `UnknownSystemAgent`);
2. нет позитивного наблюдения (heartbeat) → **`UNHEALTHY`** («never observed»);
3. heartbeat устарел (> TTL) → **`UNHEALTHY`** («stale»);
4. lifecycle не в `{READY, ACTIVE}` → **`UNHEALTHY`** / `DEGRADED` (REGISTERED).
Здоровье — сигнал готовности для routing/availability, НЕ permission, НЕ право исполнять.

## 5. Scope item 6 — Capability declaration (descriptive only) (`capabilities.py`)

- `SystemCapability` (6 токенов), `CapabilityDeclaration` (immutable),
  `CapabilitySurface` (описательный сет одного агента).
- **Задекларированная capability — metadata, не грант**: у `CapabilitySurface` нет
  grant/authorize/execute/dispatch-поверхности (тест + AST).

## 6. Scope item 7 — Coordination integration (`coordination.py`)

- `SystemAgentCoordination` связывает рантайм с Phase 2: водит `CoordinationState`,
  выбирает system-агентов через `AgentRouter` (availability = healthy set из health-модели),
  доставляет `MessageEnvelope` через `InMemoryMessageBus`.
- **Planner != executor, Supervisor != executor, AgentMessage == data**: у координации нет
  execute/dispatch/authorize/grant методов; отправка сообщения — транспорт данных.

---

## 7. Архитектурная граница (подтверждена)

- System-агенты работают **только в control plane**; прав на tool execution 0.
- Registry не расширяет production capabilities (allowlist 5 системных id).
- Lifecycle иммутабелен (fail-closed, терминальные листья).
- Health fail-closed (нет положительного сигнала → никогда зелёное).
- **Нет второго execution engine** — AST-скан `scripts/scan_system_agents.py`:
  **8 файлов, 0 kernel-импортов, 0 authority-вербов** (def + call).
- Новые модули не импортируют execution kernel и не имеют authority-поверхности.

## 8. Verification

- `compileall agent/agent_system + tests/agent_system` — **OK**.
- AST mechanical gate — **PASS** (0 kernel-импортов, 0 authority-вербов).
- Scoped canonical (`tests/agent_runtime tests/agent_orchestration tests/platform_policy
  tests/platform_persistence tests/platform_api tests/platform_memory tests/agent_system`):
  **413 passed / 0 failed** (34 файла). Phase 4 добавил **+76** (6 файлов
  `tests/agent_system`). Живой scoped-baseline предшествующих 6 папок: **337** (документ
  Phase 3 писал 332 — дрифт документации прежней фазы; файлы Phase 4 их не трогали).
- Production untouched: HEAD/ветка неизменны, staged=0, gateway `MainPID=171817/NRestarts=0`
  (не менялись), ни одного kernel/production пути не затронуто.

## 9. Acceptance gates Phase 4

| Gate | Статус |
|---|---|
| system agents работают только в control plane | ✅ (без authority-поверхности; AST 0) |
| registry не расширяет production capabilities | ✅ (allowlist 5 id; `test_registration_does_not_expand_capabilities`) |
| lifecycle immutable | ✅ (fail-closed, терминальные листья, нет flapping) |
| health model fail-closed | ✅ (нет сигнала → UNHEALTHY; stale → UNHEALTHY) |
| capability declaration ≠ authority | ✅ (CapabilitySurface без grant/execute; тест+AST) |
| AgentMessage / Memory / Planner / Supervisor не authority | ✅ (координация без execute; сообщение — данные) |
| Coding Agent mutation off | ✅ (`write_files/execute_code=False`; не может быть включено этим слоем) |
| Security review | ✅ (независимый adversarial review: BLOCKING_FINDINGS=0, 9/9 PASS, VERDICT=PASS) |
| NEW_REGRESSIONS=0 | ✅ (полный canonical: 0 phase-failures, 30 external pre-existing, 30/30 untouched, 0 coupling) |

## 10. Регрессия (фактическая, после полного canonical)

Полный canonical на исправленном коде (`scripts/run_tests.sh`):

```
=== Summary: 3151 files, 33324 tests passed, 101 failed, 285 skipped (100% complete) in 1039.1s ===
TEST_RUNNER_EXIT_CODE=1   (fail-red)
```

- **Phase 4 файлы в failures: 0** — все 6 файлов `tests/agent_system` прошли
  (76✓), ни одного FAILED.
- **30 failing файлов** — классифицированы по протоколу (два негативных чека):
  - `git diff --stat HEAD -- <file>` пуст для **30/30** (фаза их не изменяла);
  - coupling: **0** файлов импортируют `agent_system` (нет зависимости);
  - **0** failing-файлов под `tests/agent_system/`;
  - → **NEW_REGRESSIONS=0** (тот же pre-existing/ENVIRONMENTAL внешний пул:
    acp, tools/network, plugins, run_agent providers, operations_v2, hermes_cli,
    intent_router, hermes_state, live/subprocess guards).
- Полный-суite дельта Phase 3→4: files 3145→3151 (+6 — мои тест-файлы),
  passed 33247→33324 (+77, из них +76 attributable agent_system), failed 102→101.
  Несовпадение ±1 в общем счёте — флак pre-existing пула (не из Phase 4;
  set-level доказательство 30/30 untouched+coupled=0).

## 11. Секьюрити-ревью

Независимый adversarial read-only review (субагент, 8 файлов пакета + зависимые контракты
`agent_runtime`/`agent_orchestration`): **BLOCKING_FINDINGS=0, VERDICT=PASS**, все 9
acceptance-пунктов PASS (deny-by-default/обход, capability-surface без authority, контекстный
footprint, health fail-closed, координация без execute, 0 kernel-импортов/0 authority, registry
не расширяет capabilities, lifecycle immutable, cross-agent изоляция).

Неблокирующие замечания (не влияют на вердикт; отложить на будущий hardening):
1. `SystemAgentRuntime.__init__` принимает caller-supplied `AgentRegistry` и только проверяет его
   тип — не верифицирует, что allowlist registry == `SYSTEM_IMPLEMENTATION_IDS`
   (`agent_runtime.AgentRegistry` не экспонирует accessor на allowed ids). Default-путь ограничен
   фиксированными id; риск только при инъекции более широкого registry.
2. `AgentHealthModel` без lifecycle-provider (standalone) даёт HEALTHY по свежему heartbeat без
   проверки lifecycle. Рантайм всегда подаёт `lifecycle_status`, поэтому ship-путь fail-closed;
   standalone-пользователь должен передавать provider.
3. Косметика: `register` создаёт `AgentLifecycle(version=0)` при definitions version=1 — безвредно.

**Boundary:** Phase 4 ничего не активирует в production, не выполняет tools, не коммитит/
пушит/тегирует. ОСТАНОВ на Phase 4 до отдельной явной команды.