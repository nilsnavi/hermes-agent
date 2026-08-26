# Agent Orchestration Framework Hermes 2.0 — Phase 2
## Communication & Orchestration Control Plane

> **Статус:** реализовано. Дата: 2026-08-25
> Репозиторий: `~/.hermes/hermes-agent-sprint137` · ветка `sprint/1.3.7-narrow-production-canary`
> Head: `9389dea5…` (не менялся) · Pre-change backup: `~/hermes-backup-sprint-1.4-phase2-orchestration-20260825-215720` (956/956 OK)

---

## 0. Scope Phase 2 (реализовано)

| # | Scope item | Модуль | Статус |
|---|---|---|---|
| 1 | AgentMessage contract | `agent/agent_orchestration/messages.py` | ✅ новый |
| 2 | Message envelope | `MessageEnvelope` (alias `AgentMessage`) | ✅ |
| 3 | Message bus abstraction | `message_bus.py` (`MessageBus` port + `InMemoryMessageBus`) | ✅ |
| 4 | Task Analyzer | `analyzer.py` (`TaskAnalyzer`, `TaskAnalysis`) | ✅ |
| 5 | Planner | `planner.py` (`Planner`, `PlannedStep`) | ✅ |
| 6 | Agent Router | `router.py` (`AgentRouter`, `RouteSelection`) | ✅ |
| 7 | Supervisor orchestration flow | `supervisor_flow.py` (`SupervisorOrchestrationFlow`) | ✅ |
| 8 | DAG planning model | использует существующий `TaskPlan`/`TaskStep`/`TaskGraph` | ✅ |
| 9 | Agent coordination state machine | `coordination.py` (`CoordinationState`) | ✅ |

Все модули — pure contracts / stdlib-only, без импорта execution kernel, без authority.

---

## 1. AgentMessage / MessageEnvelope (items 1-2)

`messages.py`:
- `MessageType` (REQUEST/RESPONSE/EVENT/FEEDBACK/ERROR) — 5 canonical типов.
- `MessagePriority` (LOW/NORMAL/HIGH/CRITICAL).
- `MessageEnvelope` — immutable, bounded: message_id, schema_version, from/to_agent,
  type, priority, task_id, step_id, run_id, correlation_id, causation_id,
  idempotency_key, payload (tuple ≤128), expires_at.
- **AgentMessage не authority**: envelope — данные, не грант. Нет execute/run/authorize/grant.
- Валидация fail-closed: non-empty IDs, positive schema_version, enum-типы, bounded payload,
  non-negative expires_at.

## 2. Message bus (item 3)

`message_bus.py`:
- `MessageBus` port (`publish`, `consume_next`).
- `InMemoryMessageBus` — thread-safe in-memory adapter, per-consumer inbox isolation,
  `consume_effective` дедуплицирует на `(consumer, message_id)`, пропускает expired.
- **Bus не выполняет tools**: только доставка валидированных envelopes. Нет
  execute/run/authorize/grant поверхностей. Обозначено в docstring.

## 3. Task Analyzer (item 4)

`analyzer.py`: детерминированная классификация цели → `TaskAnalysis` (goal, task_id,
suggested_capabilities, read_only, requires_verification). Только сигнал; без I/O и
authority. Weak vocabulary — Planner применяет policy, не словарь.

## 4. Planner + DAG planning (items 5, 8)

`planner.py`: `Planner.plan(analysis, ..., steps, available_capabilities)` →
`TaskPlan` (model) → валидация `TaskGraph`. Capability gate: план, требующий
недоступной capability, отклоняется (`InvalidPlan`). **Planner только создаёт план**;
не исполняет, не диспатчит, не даёт authority. DAG (`TaskGraph`) — только граф
готовности, без execution-поля.

## 5. Agent Router (item 6)

`router.py`: `AgentRouter.route(required_capability, availability)` → `RouteSelection`.
Hard gates (capability присутствует, availability если задан, version активна,
trust>0) ДО deterministic score (0.35/0.20/0.20/0.15/0.10). **Router только выбирает**;
не исполняет, не диспатчит. Tie-break по agent_id — детерминированно.

## 6. Supervisor orchestration flow (item 7)

`supervisor_flow.py`: `SupervisorOrchestrationFlow.run(ctx, router, ...)` сводит
`SupervisorPolicy.decide` (существующий fail-closed классификатор) с Router для
alternative-маршрута. HUMAN_REVIEW для UNKNOWN/TIMEOUT/side-effect; ALTERNATIVE
только через router (нет слепого dispatch); нет eligible alternative → ESCALATE.
`to_escalation_event` — typed sink. **Supervisor только управляет состояниями**; не исполняет.

## 7. Agent coordination state machine (item 9)

`coordination.py`: `CoordinationStatus`
(ANALYZING→PLANNING→ROUTING→SUPERVISING→VALIDATING→COMPLETED/FAILED/CANCELLED),
терминальные иммутабельны, illegal transition → `InvalidCoordinationTransition`.
Чистый state machine без authority.

---

## 8. Архитектурная граница (подтверждена)

- **Message Bus не выполняет tools** — только доставка envelopes.
- **Router только выбирает** — нет dispatch/execute.
- **Planner только создаёт планы** — нет исполнения.
- **Supervisor только управляет состояниями** — нет исполнения.
- **Task DAG не содержит execution authority** — `TaskGraph` только готовность.
- **Второй execution engine отсутствует** — AST scan: 0 импортов
  subprocess/os.system/systemctl/VerifiedToolExecutor/RuntimeOrchestrator/execution/
  recovery/sandbox/capability_router во всех новых файлах.
- **AgentMessage/Planner/Supervisor/Memory не authority** — ни в одном модуле нет
  authority-поверхности (execute/dispatch/authorize/grant).

## 9. Verification

- `compileall` — OK.
- Scoped canonical (`scripts/run_tests.sh tests/agent_runtime tests/agent_orchestration
  tests/platform_policy tests/platform_persistence tests/platform_api`):
  **295 passed / 0 failed** (23 файла). Phase 2 добавил +53 (Phase 1 было 242).
- Production untouched: Kernel modified = NONE; HEAD не менялся; gateway PID=171817/NRestarts=0.
- Полный canonical: см. "Регрессия".

## 10. Acceptance gates Phase 2

| Gate | Статус |
|---|---|
| Message Bus не выполняет tools | ✅ (нет execute поверхностей; AST 0) |
| Router только выбирает agents | ✅ (нет dispatch; скорость+hard gates) |
| Planner только создаёт планы | ✅ (нет execute/dispatch) |
| Supervisor только управляет состояниями | ✅ (нет execute; только disposition) |
| Task DAG не содержит execution authority | ✅ (TaskGraph — только граф) |
| Нет второго execution engine | ✅ (0 kernel импортов) |
| Security review | ✅ (независимый adversarial review: BLOCKING_FINDINGS=0, VERDICT=PASS) |
| NEW_REGRESSIONS=0 | ✅ (полный canonical: 0 phase-failures, 30 external pre-existing) |

## 11. Регрессия (фактическая, после полного canonical)

Полный canonical (`scripts/run_tests.sh`):

```
=== Summary: 3140 files, 33207 tests passed, 100 failed, 285 skipped (100%) in 1043.2s ===
FULL_CANONICAL_EXIT=1   (fail-red)
```

- **Phase 1/2 файлы в failures: 0** (`platform_policy/persistence/api`, `agent_runtime`, `agent_orchestration` и их тесты — ни одного).
- **30 failing файлов** — все внешние (acp, tools/network, plugins/memory+video+image, run_agent provider-routing, operations_v2, hermes_cli, intent_router, hermes_state, live_system_guard/subprocess_stdin_guard, wecom):
  - **0** с non-empty git diff (`git diff --stat HEAD` пуст) → фаза их не изменяла;
  - **0** импортирующих phase-модули (`platform_*`, `agent_runtime`, `agent_orchestration`) → нет coupling;
  - → **NEW_REGRESSIONS=0** (pre-existing/ENVIRONMENTAL сетевые/провайдерные/плагинные failures; тот же пул, что в Phase 1: 30 файлов).