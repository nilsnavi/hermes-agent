# Multi-service execution canary: foundation 1.3.18

## Назначение и граница Sprint

Sprint 1.3.18 реализует, тестирует и документирует `agent.multi_service_execution_canary`. Это default-off foundation, а не разрешение production execution. Сертифицированный baseline: `672b5aadd1d6fab61274c2d8cba31b7174954b06`. Capability строго связана с `HERMES_MULTI_SERVICE_EXECUTION_CANARY`, операция — `SIMULATE_TWO_REGISTERED_AUX_SERVICES`.

**REAL EXECUTION DISABLED. SYSTEM_CONTROL OFF.** Ни admission, ни simulated child outcome, ни durable receipt не дают право вызвать `systemctl`, shell, process, network, database или произвести global production commit.

## Authority boundaries

1. Публичный caller может создать `ProductionCanaryRequest`, прочитать registry и вызвать `CanaryPipeline.evaluate()`.
2. `ProductionCanaryAuthority` создаётся только `CanaryRuntime`; публичный constructor отклоняется. Authority привязана к runtime instance, semantic request key и одноразовому nonce.
3. Child adapter sealed, не экспортирован публичным package API и не инъецируется через `build_canary_pipeline()`.
4. `real_execute()` всегда возвращает `DENIED`; `real_execution_permitted()` всегда `False`.
5. Request и `ChildExecutionIntent` не содержат `command`, `argv`, `shell`, `unit`, `signal`, `path` или иных generic execution primitives.
6. `GLOBAL_COMMITTED_SIMULATED` означает только завершённую симуляцию. Поле `real_global_commit` остаётся `False`.

## Exact two fixtures

Registry содержит ровно два Hermes-owned, non-systemd execution fixture:

| `service_id` | `identity` | класс | критичность | fixture kind |
|---|---|---|---|---|
| `canary-service-a` | `hermes-owned-fixture-a-v1` | `HERMES_AUXILIARY` | `LOW` | `NON_SYSTEMD_EXECUTION_FIXTURE` |
| `canary-service-b` | `hermes-owned-fixture-b-v1` | `HERMES_AUXILIARY` | `LOW` | `NON_SYSTEMD_EXECUTION_FIXTURE` |

Другой размер множества, duplicate, unknown service или gateway/system service отклоняется. Нормализация сортирует IDs, но требует точного равенства authoritative set. Execution order: `a → b`; simulated compensation order: `b → a`. Registry и graph digest входят в request binding.

## Simulation semantics

`shadow` и `canary` разрешают только simulation при одновременно включённом `HERMES_MULTI_SERVICE_CANARY_V2_ENABLED`. Неизвестный mode преобразуется в `off`. Adapter возвращает только `SIMULATED_SUCCESS`, `SIMULATED_FAILURE` или `SIMULATED_UNKNOWN`; неизвестная строка нормализуется в `SIMULATED_UNKNOWN`. Успех обоих child fixtures может дать `GLOBAL_COMMITTED_SIMULATED`, но не реальный commit. Failure и post-adapter gate failure ведут в `COMPENSATION_REQUIRED_SIMULATED`; `UNKNOWN` ведёт в `UNKNOWN_OUTCOME` без автоматического retry.

## Durable state

Semantic idempotency key связывает baseline, generation, отсортированное service set, registry/graph digest, plan, operation, risk и blast. `request_id` и `approval_id` не меняют semantic key. Terminal receipt replayed с `adapter_call_count=0`. Durable store хранит claims, receipts, budget counters, approval IDs и kill switch; запись выполняется atomic replace.

## Точные prerequisites будущей live-активации

- Нет production child executor и нет пути реального global commit — это намеренная граница.
- Есть только read-only CLI `agent.multi_service_execution_canary.cli` с `status`, `inspect-plan`, `inspect-receipt` и `dry-run`; mutator verbs отсутствуют.
- Есть fail-closed recovery classifier и crash-evidence facade, но нет recovery/compensation executor: доступны только terminal classification и simulated compensation order.
- Approval имеет full-contract hash binding. Дополнительные boolean gates (`identity_valid`, `approval_valid`, `budget_available`, `locks_available`, health flags) являются только authority-reducing kill inputs: значение `True` не обходит внутренние exact registry/baseline/graph/approval/store checks, а `False` может только запретить admission. Для будущего live-canary потребуются signed/durable evidence objects.
- Lock model представлен admission boolean и in-process store lock; cross-process lease/owner/liveness API отсутствует.
- Budget — aggregate store counters; нет отдельных per-child reservations/receipts и atomic two-budget reservation API.
- Approval ID сохраняется, но single-use approval authority и независимая проверка двух child approvals отсутствуют.
- Телеметрия process-local и scalar-only; durable audit truth — receipt, доступный через read-only CLI inspector.
- Durable `active_slot` атомарно резервирует единственную simulation transaction для разных semantic keys; 100 overlapping intents дают не более одного simulator. Для будущего live-canary этот primitive должен быть заменён сертифицированной cross-process lease/owner моделью.
