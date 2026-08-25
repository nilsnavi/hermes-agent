# Multi-service execution canary: runbook 1.3.18

## Статус

Это runbook для offline tests и read-only inspection foundation. Он **не** является инструкцией для live service mutation. Real execution запрещён, `SYSTEM_CONTROL OFF`, exact two fixtures не являются systemd units.

## Предварительные проверки

1. Убедиться, что repo baseline включает `672b5aadd1d6fab61274c2d8cba31b7174954b06`.
2. Проверить, что изменения ограничены authoritative set Sprint 1.3.18: `agent/multi_service_execution_canary/`, `tests/multi_service_execution_canary/`, тремя docs 1.3.18 и тремя codemap-файлами.
3. Проверить default-off: без explicit env `enabled({}) == False`, `mode({}) == "off"`, real execution всегда false.
4. Не запускать `systemctl`, gateway restart, shell adapter или live probes: они не нужны и не разрешены.

## Канонический test gate

Из корня repo:

```bash
HERMES_TEST_WORKERS=8 .venv/bin/python scripts/run_tests_parallel.py tests/multi_service_execution_canary/
```

Ожидаются GREEN существующие RED-contract tests и новые suites: flags, service set, admission, adapter, idempotency, locks/budget/approval, recovery, shadow, rehearsal, concurrency, negative matrix, telemetry, performance, CLI absence, read-only и security.

## Как читать решения

| Решение | Операторская трактовка |
|---|---|
| `CANARY_DISABLED` | flags или kill switch закрыли canary; ничего не исполнялось |
| `DENIED` | binding/gate/authority не пройдены; до adapter либо без real effect |
| `REVALIDATE_REQUIRED` | baseline/registry/graph/TTL evidence устарело |
| `GLOBAL_COMMITTED_SIMULATED` | simulation terminal; **не** production commit |
| `COMPENSATION_REQUIRED_SIMULATED` | требуется анализ simulated recovery; compensation не выполнена |
| `UNKNOWN_OUTCOME` | terminal UNKNOWN; не retry автоматически, real state не утверждать |

## Проверка exact two fixtures

Допустимы только `canary-service-a` и `canary-service-b` с identities `hermes-owned-fixture-a-v1` и `hermes-owned-fixture-b-v1`. Их fixture kind — `NON_SYSTEMD_EXECUTION_FIXTURE`. Любая попытка подставить gateway/system service, третий service, duplicate либо неполный set должна дать deny до child simulation.

## Проверка safety state

После isolated successful simulation прочитать test store `canary-store.json` только в temp directory:

- один terminal receipt;
- `budget_attempts=1`, `budget_success=1`;
- один recorded `approval_id`;
- `kill_switch=true`;
- `real_effect_count=0`, `real_global_commit=false`.

Повтор того же semantic intent должен быть replay с нулём adapter calls. Новый intent, начатый после terminal write, должен получить persisted kill-switch deny. Для разных overlapping keys durable `active_slot` допускает не более одного simulator; остальные получают `CANARY_DISABLED`, а после terminal следующий intent также блокируется persisted kill switch. Failure должен дать simulated compensation order; UNKNOWN должен стать terminal и не повторяться.

## Диагностика

- `flags-off`: проверить explicit `ENABLED` и mode; неизвестный mode считается `off`.
- `service-set`: сверить exact two fixtures, без aliases.
- `baseline-drift`, `registry-drift`, `graph-drift`, `expired`: получить новую read-only evidence и повторно оценить; не ослаблять gate.
- `gate`: отдельно проверить approval, budget, all-locks, system-control-off, generic-control-denied, real-adapter-disabled.
- `claimed-by-other`: дождаться terminal receipt либо расследовать abandoned claim; не запускать второй adapter.
- `unknown-no-retry`: остановиться, сохранить evidence, не считать успехом/ошибкой и не выполнять автоматическую compensation.

## Kill switch и остановка

Безопасное состояние — flags off. Persisted kill switch уже закрывает новый intent после terminal scenario. Не удалять/редактировать store ради обхода. Любая процедура reset kill switch должна быть отдельным future change с operator approval, backup, durable audit и atomic recovery semantics.

## Future prerequisites для реального canary

До любого live execution необходимы отдельные спринты и новые public contracts:

1. cryptographically/durably bound, single-use approvals для каждого child и global plan;
2. atomic per-child + global budget reservation/commit/rollback;
3. cross-process canonical lock set с owner PID/start identity, lease renewal и stale-owner recovery;
4. sealed production adapter с exact typed operations и отсутствием generic command surface;
5. durable coordinator authority, global commit token и независимая postcondition verification;
6. real recovery state machine, snapshots, rollback и compensation receipts;
7. строгая UNKNOWN policy: no retry, manual review, reconcile/observe path;
8. durable read-only CLI/API для receipts, claims, budget, approvals и kill switch;
9. crash/process-death/partial-effect/TOCTOU/host-reboot tests;
10. shadow study на production-shaped evidence без effects, rehearsal с fake adapter, затем отдельное explicit operator approval для live canary;
11. security review всех private factories/constructors и independent authority-sealing audit;
12. documented rollback, bounded stability window и доказательство отсутствия изменений gateway/scheduler/provider/database.

Пока эти prerequisites отсутствуют, результат Sprint 1.3.18 остаётся simulation-only foundation.
