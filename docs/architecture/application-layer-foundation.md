# Hermes application-layer foundation

Дата: 2026-09-19.

Создан изолированный пакет `hermes_core/`. Он содержит только domain values, application services и Protocol-порты. Существующие `gateway/`, `agent/`, `tools/`, `hermes_state*`, `cron/`, TUI и provider adapters не импортируются и не изменяются. Новый слой не подключён к runtime, поэтому текущая функциональность и API остаются прежними.

## 1. New layers

```text
hermes_core/
├── domain/
│   ├── session.py       # SessionId, SessionKey, Session, lease/generation state
│   ├── delivery.py      # DeliveryState and obligation transitions
│   └── routing.py       # RoutePurpose and immutable RouteDecision
├── ports/
│   ├── persistence.py   # PersistencePort and SessionRepository
│   ├── delivery.py      # DeliveryPort
│   ├── providers.py     # ProviderPort
│   └── tools.py         # ToolExecutorPort
└── application/
    ├── session_service.py
    ├── execution_service.py
    ├── delivery_service.py
    ├── provider_router.py
    └── runtime_application.py
```

`RuntimeApplication` оркестрирует входное событие: session ownership → provider route → последующий execution/persistence/delivery через сервисы и порты. В текущем foundation оно планирует session и route и освобождает lease; фактическая inference/tool/transport реализация намеренно отсутствует.

`SessionService` владеет create/resume/close и lease generation, но принимает `PersistencePort`. `ExecutionService` проверяет базовый контракт имени и передаёт вызов `ToolExecutorPort`; subprocess, registry и approval implementation находятся вне слоя. `DeliveryService` проводит pending → attempting → delivered/failed и получает только `DeliveryPort`. `ProviderRouter` возвращает `RouteDecision` с provider, model, endpoint, api_mode, credential reference и route purpose; SDK и секреты ему неизвестны.

### Hardened contracts

- `Session.generation` — версия изменений состояния сессии; `Session.lease_generation` — версия владения lease. Методы `acquire_lease()` и `release_lease()` используют отдельный lease generation для защиты от устаревших владельцев. Метод `close(owner, lease_generation)` разрешает закрытие только текущему владельцу lease и не позволяет stale owner изменить активную сессию.

- `DeliveryResult` — immutable результат транспорта с `success`, `external_id`, `retryable` и `error`. `DeliveryService` переводит delivery obligation в `delivered` только после подтверждённого успешного результата. Retry decision остаётся ответственностью будущего orchestration слоя.

- `ToolExecutionContext` — immutable контекст вызова, содержащий `session_id`, `turn_id`, `tool_call_id`, `capability_grant` и `approved`. `ToolExecutorPort` принимает полный контекст выполнения вместо отдельного boolean-флага.

- `RouteDecision` остаётся `@dataclass(frozen=True)`. В маршрут передаётся только `credential_reference`; реальные секреты и SDK clients остаются вне application/domain слоя.

## 2. Dependency rules

Направление зависимостей:

```text
ports/interfaces → application services → domain values/state → infrastructure adapters
```

Domain-модули используют только стандартную библиотеку и собственные типы. Application-модули зависят от domain и Protocol-портов. В `hermes_core` запрещены импорты gateway, `hermes_state`, `sqlite3`, `os.environ`, provider SDK, FastAPI, platform adapters, subprocesses и существующих tool registries. Infrastructure adapters в будущем реализуют порты снаружи этого слоя.

Порты описывают capability, а не реализацию: `PersistencePort` не раскрывает SQLite connection/WAL; `ProviderPort` не возвращает SDK client; `DeliveryPort` не решает, когда obligation считается acknowledged; `ToolExecutorPort` не исполняет команды сам. Профиль, authorization и OS isolation должны передаваться через явные контексты будущих адаптеров, а не выводиться из process environment.

Concurrency assumptions: один lease owner изменяет конкретную сессию за раз; устаревший owner обязан получить `False` от `release_lease()` или `close()` при несовпадении `lease_generation`; persistence adapter сериализует сохранение и обеспечивает атомарность своих операций.

## 3. Current runtime compatibility

Совместимость достигается отсутствием integration points. Ни один существующий модуль не импортирует `hermes_core`, а новый пакет не меняет регистрацию tools, gateway startup/shutdown, SessionDB schema, provider precedence, delivery ledger или TUI RPC.

Domain state намеренно отражает важные текущие контракты: lease проверяет owner и monotonic generation; закрытие очищает lease; delivery нельзя подтвердить до `attempting`; route содержит purpose и credential reference вместо credential value. Это архитектурные значения, а не замена текущих `SessionState`, `delivery_ledger.py` или resolver.

Существующие runtime остаются authoritative. В частности, новая `SessionRepository` не реализует `hermes_state`, `ProviderPort` не вызывает `runtime_provider`, `DeliveryPort` не оборачивает gateway ledger, а `ToolExecutorPort` не вызывает `model_tools`. Подключение этих компонентов — отдельная миграция с regression harness и ownership gates.

## 4. Future migration path

1. Сначала зафиксировать golden baseline из `docs/architecture/regression-harness-plan.md` и проверить, что импорты foundation не создают циклов.
2. Добавить внешние adapters для persistence и delivery, не меняя их существующих владельцев; доказать WAL/generation и delivery crash contracts.
3. Подключить `SessionService` к repository adapter после проверки create/resume/close, stale lease, generation и compression lineage.
4. Подключить `ProviderRouter` как фасад существующего resolver с сохранением lazy precedence, credential scope, auxiliary purpose и fallback semantics.
5. Подключить `ExecutionService` к существующим inline/registry путям только после parity-проверок approval, hooks, concurrent scheduling и result persistence.
6. Подключить `RuntimeApplication` к одной поверхности за раз (сначала изолированный controller), затем gateway/TUI/cron; удалить старые владельцы только после receipts и rollback proof.

Contract hardening precedes every adapter: сначала адаптеры должны научиться сохранять отдельные session/lease generations, возвращать `DeliveryResult`, передавать immutable `ToolExecutionContext` и строить полный immutable `RouteDecision`; только после этого возможна интеграция с прежними runtime владельцами.

Каждый шаг обязан проходить `scripts/run_tests.sh` для затронутого домена, real-import checks с временным `HERMES_HOME`, применимые lifecycle/security gates и paired evals. До подключения новый пакет остаётся пассивным архитектурным контрактом.

## Validation performed

После hardening выполнены `python -m compileall hermes_core`, импорт всех новых модулей и проверка отсутствия импортов `gateway`, `hermes_state`, `sqlite` и provider SDK. Проверки production runtime и существующая тестовая suite этим заданием не запускались и не изменялись.
