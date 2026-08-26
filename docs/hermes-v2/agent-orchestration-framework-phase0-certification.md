# Agent Orchestration Framework Hermes 2.0 — Phase 0
## Architecture Freeze & Control Plane Boundary Certification

> **Статус: CERTIFIED (Phase 0 PASS)**
> Дата: 2026-08-25 · Репозиторий: `~/.hermes/hermes-agent-sprint137`
> Ветка: `sprint/1.3.7-narrow-production-canary` · HEAD: `9389dea5aafd…` (tag `hermes-v2-multi-service-execution-canary-1.3.18`)
> Автор certification: документальный read-only артефакт; **zero implementation source** создано этой фазой.

---

## 0. Санкции Phase 0 (соблюдены дословно)

| Ограничение | Факт |
|---|---|
| не создавать implementation source files | ✅ создан единственный файл — настоящий certification-документ (`.md`), не импортируется, не является исполняемым кодом; phase-1 модули (`agent/agent_runtime`, `agent/agent_orchestration`) — pre-existing untracked из прошлой сессии, НЕ изменены |
| не изменять production runtime | ✅ gateway не тронут (см. §6) |
| не менять execution kernel | ✅ `agent/runtime`, `agent/orchestrator`, `agent/execution`, `agent/verified_tool_executor`, `agent/system_boundary`, `agent/sandbox_runtime`, `agent/capability_router` не изменялись |
| не включать Coding Agent mutation capabilities | ✅ Coding Agent остаётся read-only/shadow до защиты execution composition (§5) |
| не делать commit/tag/push | ✅ **не выполнялось**; работа остаётся в working-tree как untracked |
| не выполнять production activation | ✅ никаких флагов/системных изменений |

---

## 1. Зафиксированные bounded contexts

Архитектурный документ `docs/hermes-v2/agent-orchestration-framework-architecture.md` (§2) определяет **7 bounded contexts**. Каждому зафиксирован внешний контракт, authority и readiness:

| # | Bounded context | Contract | Authority | Readiness |
|---|---|---|---|---|
| 1 | **Agent Runtime** | `BaseAgent` (id/role/capabilities/trust/permissions), registry, quality | регистрация + метаданные агентов; **не** выполняет | проектные module `agent/agent_runtime` (domain-only) |
| 2 | **Orchestration Control Plane** | Task lifecycle, DAG, routing, supervision, message flow | решает *кто/когда/почему* | проектные module `agent/agent_orchestration` (domain-only) |
| 3 | **Execution Kernel** | existing runtime/orchestrator/execution/security | решает *можно ли/как безопасно выполнить tool action* | **уже существует и сертифицирован** (спринты 1.0–1.3.18) |
| 4 | **Memory Intelligence** | scoring, retention, retrieval, consolidation, context building | Memory Controller — authority записи | не создан (Phase 4) |
| 5 | **Platform Persistence** | PostgreSQL repositories, migrations, transactional outbox | PostgreSQL — authoritative platform store | не создан (Phase 3) |
| 6 | **Platform API** | authenticated REST surface | аутентифицированный principal | не создан (Phase 7) |
| 7 | **Observability & Audit** | events, metrics, traces, redacted audit | append-only audit chain | не создан (Phase 8) |

**Границы контекстов непроницаемы** в правильном направлении: execution kernel никогда не поднимается в control plane; control plane никогда сам не выполняет tool — только через execution kernel adapter.

---

## 2. Control Plane → Execution Kernel boundary (подтверждена)

Принцип зафиксирован дословно (архитектурный документ §3):

> «Control plane решает **кто, когда и почему** выполняет работу. Existing execution kernel решает **можно ли и как безопасно выполнить tool action**. AgentMessage, AgentDefinition или trust score никогда не дают execution authority.»

### Что это означает на уровне authority

- **Task / TaskStep** — сущности control plane. Один Task может иметь несколько `AgentRun` (parallel / retry / alternative agent). Task не содержит тулов и не имеет права их вызывать.
- **AgentRun / Run / Attempt** — сущности execution kernel. Долгоживущие бизнес-цели (Task) отделены от отдельных попыток выполнения (AgentRun). Сохраняется существующая authority execution kernel (receipts, idempotency, `UNKNOWN_OUTCOME`, approval).
- **Каналы связи** (`AgentMessage`, `AgentMessage` bus) — транспорт, **не authority**: даже если сообщение «приказывает» выполнить действие, сам факт его доставки не даёт права выполнить tool. Право исполнения приходит только из verified executor + system boundary + policy.
- **trust score / AgentDefinition** — сигналы маршрутизации, не permission. Permissions вычисляются как пересечение `requested ∩ granted ∩ tenant/platform policy ∩ tool/capability policy` (default deny).

### Точки интеграции (seam), где control plane касается kernel (архитектурный документ §14)

1. `agent/agent_orchestration/engine.py` вызывает existing `RuntimeOrchestrator` **через adapter**, не импортирует tool handlers напрямую.
2. `PlannerAgent` компилирует DAG-узел в existing `TaskContext` + explicit `step_specs`.
3. Agent Router использует `agent/capability_router` + отдельный `AgentRegistry` — **два разных domain, не дублируются**.
4. `CodingAgent` получает только sandbox-bound tools через `verified_tool_executor` + `sandbox_runtime`.
5. `Supervisor` использует existing recovery dispositions и receipts; `UNKNOWN_OUTCOME` всегда → human review.
6. `Memory Intelligence` реализует `MemoryProvider` adapter для существующего `MemoryManager` seam.

**Boundary = jedna z официальных точек интеграции, НЕ избыточный параллельный kernel.**

---

## 3. Проверка отсутствия второго execution engine

Механическая проверка всех files существующих phase-1 модулей (`agent/agent_runtime/` 7 файлов, `agent/agent_orchestration/` 4 файла) + их тестов:

- Импорты: **только** stdlib — `abc, dataclasses, math, re, enum, copy, collections, typing`. 
- Импортов execution/IO-подсистем: `subprocess, os, sys, eval, exec, importlib, asyncio, aiohttp, sqlite3, psycopg, redis, httpx, requests, socket` → **0**.
- Вызовов исполнения: `execute, run, Popen, spawn, system` → **0**.
- Импортов существующих engine-модулей: `VerifiedToolExecutor, RuntimeOrchestrator, ExecutionRuntime, tool_registry, adapter, systemctl, crontab` → **0**.

**Вывод:** ни `agent_runtime`, ни `agent_orchestration` **не содержат и не строят второй исполняющий движок**. Они — чистые domain-модели и state machine (`BaseAgent`, `AgentRegistry`, `Task`, `TaskGraph`, `TaskStatus`). Любое фактическое выполнение делегируется существующему сертифицированному kernel (bounded context #3). Это соответствует жёсткому правилу протокола: «новый слой должен агрегировать и повторно валидировать доказательства существующих certified слоёв, не создавать альтернативный executor/engine».

---

## 4. Утверждённые security boundaries

Из архитектурного документа §9 (утверждается целиком):

1. **Default deny** — permission model (`read_files / write_files / execute_code / network_access / memory_read / memory_write / agent_message_send`) закрыта по умолчанию; ничего не открывается, пока не разрешено.
2. **Агент не mint-ит право**: `AgentDefinition` не принимает произвольный Python import path или executable command из API; implementation IDs идут только из allowlisted code/plugin registry.
3. **Immutable bounded execution context**: `AgentExecutionContext` immutable, содержит только task/step/run IDs, sanitized input/context, memory references, deadline, permission grant reference, idempotency key, approved tool surface. **Не содержит** credentials, raw system prompt, прямых executors.
4. **Один production execution boundary**: инструменты исполняются **только** через `VerifiedToolExecutor` + `SystemBoundaryLayer`; Coding Agent через `sandbox_runtime`. Никакого прямого shell-пути.
5. **Coding Agent мутационные capabilities выключены** до прохождения hardening gate: «До прохождения gate Coding Agent работает только в read-only/shadow режиме» (§9). Это и есть санкция «не включать Coding Agent mutation capabilities».
6. **Prompt/memory = untrusted data**: не может изменить permissions.
7. **Secrets** не попадают в task context, messages, memory, logs, embeddings.
8. **Audit append-only**; admin delete/register записываются.
9. **Изоляция**: отдельный worker context + immutable context + bounded tool registry; один in-process Python object **не** считается security boundary.

### Security hardening gate (пусковой критерий для Coding Agent)
Задокументирован §9: до enable `CodingAgent.write_files/execute_code` необходимо (1) сделать boundary обязательной (не `None`), (2) связать Capability Router → Policy → System Boundary → Verified Tool Executor → Sandbox Adapter в одном composition root, (3) запретить caller-supplied verdict/approval, (4) добавить adversarial bypass tests. До этого — **read-only/shadow**. План включает отдельную задачу **Task 5.0 «Harden production execution composition»** именно под этот gate.

---

## 5. Модель authority: что НЕ входит в Phase 0 / Phase 1

Зафиксировано для предотвращения дрейфа:

| Сущность | Имеет authority на выполнение? | Где |
|---|---|---|
| Task / TaskStep | нет (control plane) | agent/agent_orchestration |
| AgentMessage | нет (транспорт) | agent/agent_orchestration |
| AgentDefinition / trust score | нет (сигнал) | agent/agent_runtime |
| Supervisor (retry/alternative/escalation) | только решает путь, не выполняет | будущий |
| VerifiedToolExecutor | **да** (единственный production boundary) | существующий kernel |
| SystemBoundaryLayer | **да** (policy gate) | существующий kernel |
| SandboxRuntime | **да** (sandbox mutation) | существующий kernel (после hardening) |

---

## 6. Pre-change baseline (production-untouched proof)

Снято read-only до любых действий Phase 0 (истина — состояние на момент certification):

- **Gateway** — НЕ рестартовался, НЕ менялся, никаких systemd/config флагов.
- **Execution kernel** — все существующие модули (`agent/{runtime, orchestrator, execution, verified_tool_executor, system_boundary, sandbox_runtime, capability_router}`) present и не изменялись.
- **Working tree** — чистый по production-пути; единственные untracked — phase-1 модули framework (`agent/agent_runtime/`, `agent/agent_orchestration/`, `tests/agent_runtime/`, `tests/agent_orchestration/`) **pre-existing из прошлой сессии**, плюс известные uncommitted многосервисные codemap/execution правки.
- **Ничего не staged** (`git diff --cached` пуст), **ничего не закоммичено**.
- **`git status`** до/после Phase 0 не изменился (кроме добавленного настоящего документа).

---

## 7. Подготовлен безопасный переход к Phase 1 (Platform Foundation)

Готовность к фазе 1 подтверждена следующими условиями, все выполнены:

1. Архитектура (bounded contexts, boundary, authority модель) **заморожена** — документ в репо, sha зафиксирован.
2. Второго execution engine **нет** — установлено механически.
3. Security boundaries **утверждены** (default deny, immutable context, single execution boundary, Coding Agent read-only).
4. Phase 1 модули уже существуют как **domain-only untracked** (из прошлой сессии) и требуют только running canonical tests + независимого review до объявления PASS.
5. **Пусковой критерий:** Phase 1 может быть запущена **только отдельной явной командой** пользователя (не считается активированной этим документом).

### Что осталось вне Phase 0 (будущие фазы)
- Phase 1: domain contracts + state machines (агент runtime, registry, quality, Task/DAG).
- Task 5.0: защита production execution composition (обязательна до Coding Agent).

---

## 8. Итог

```
PHASE 0 RESULT
STATUS: PASS
CONTEXT: Agent Orchestration Framework Hermes 2.0
SCOPE:   Architecture Freeze & Control Plane Boundary Certification (design-only)
BOUNDED CONTEXTS: 7 зафиксированы (§1)
CP → EK BOUNDARY:  подтверждена — control plane решает кто/когда/почему;
                   execution kernel решает можно ли/как; AgentMessage/AgentDefinition/
                   trust score НИКОГДА не дают execution authority (§2)
SECOND ENGINE:     ОТСУТСТВУЕТ — 0 execution/IO импортов в agent_runtime+agent_orchestration (§3)
SECURITY BOUNDARY: утверждены — default deny, immutable context, single execution
                   boundary, Coding Agent read-only/shadow до hardening gate (§4)
PRODUCTION:        НЕ ТРОНУТО — gateway/kernel/config без изменений (§6)
COMMIT/TAG/PUSH:   НЕ выполнен
CODING MUTATION:   capabilities НЕ включены
FILES CREATED:     docs/hermes-v2/agent-orchestration-framework-phase0-certification.md (документ)
REGRESSION:        не применимо (0 implementation source; тесты phase-1 — вне Phase 0)
NEXT STEP:         ОСТАНОВ. Ожидается отдельное явное подтверждение Phase 1
                   (Platform Foundation) до любых source-изменений.
```

**ДЕЙСТВИЕ: ОСТАНОВЛЕН на Phase 0 Certification. Жду отдельного подтверждения Phase 1 (Platform Foundation). Никаких implementation source, commits, tags, pushes, production активаций до явной команды.**