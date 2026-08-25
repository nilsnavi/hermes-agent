# Multi-service execution canary: safety 1.3.18

## Инвариант безопасности

Foundation оценивает production-shaped evidence, но исполняет только детерминированную симуляцию над exact two fixtures. Любая неоднозначность закрывается fail-closed. Ни один результат не является production authority.

## Admission ladder

Порядок проверок важен:

1. exact authoritative service set; gateway, scheduler, provider, database, network, auth, security, container и unknown IDs запрещены;
2. exact baseline SHA;
3. registry digest;
4. graph digest и `graph_healthy`;
5. TTL;
6. operation/risk/blast binding;
7. identity evidence;
8. persisted и caller kill switch;
9. approval, budget, all-locks, `SYSTEM_CONTROL OFF`, generic service-control deny и real-adapter-disabled;
10. permanent `real_execution_permitted() == False`.

До прохождения ladder child simulation calls равны нулю. `GLOBAL_COMMITTED_SIMULATED` допустим только после simulation и post-adapter verify/health/stabilization gates.

## Kill switch

После первого terminal simulation store атомарно устанавливает `kill_switch=true`. Новый semantic intent в том же root получает `CANARY_DISABLED` до adapter. Переданный caller `kill_switch_off=True` не может обойти persisted state. Rollback для foundation — оставить flags в `off` или `enabled=false`; production restart для этого не требуется и этим Sprint не разрешён.

## Approval, budget и locks

- `approval_valid=False`, `budget_available=False` или `locks_available=False` дают global deny до первого child call.
- Успешный terminal receipt увеличивает `budget_attempts` на один, `budget_success` на один и сохраняет `approval_id`.
- Встроенные caps: не более 10 attempts и 5 successes, однако persisted kill switch делает текущий canary ещё уже: один terminal scenario на root.
- `locks_available` означает «получено полное множество locks до начала». Частичное child execution при недоступном втором lock запрещено.
- Текущий API не моделирует две независимые approval capability, две budget reservation и cross-process lock lease. Boolean gates — testable contract, но не production-grade proof.

## Idempotency и concurrency

Claim создаётся по semantic intent. Одновременные coordinators для одного key имеют максимум одного simulator; остальные bounded-wait читают terminal replay. Terminal replay сохраняет исходное решение, child outcomes и compensation order, имеет `adapter_call_count=0`. Обратный порядок exact service IDs сводится к тому же key. Для **разных** overlapping keys durable `active_slot` атомарно резервирует единственную simulation transaction; остальные получают `CANARY_DISABLED`. После terminal persisted kill switch блокирует новые intents.

## Recovery, compensation и UNKNOWN

- Failure на `a` останавливает forward order; failure на `b` сохраняет два child outcomes.
- Failure либо post-adapter verify/health/stabilization failure классифицируется как `COMPENSATION_REQUIRED_SIMULATED` с reverse order `b → a`.
- Compensation — только immutable simulation evidence. `real_compensation_adapter_calls` всегда ноль.
- `SIMULATED_UNKNOWN` превращается в terminal `UNKNOWN_OUTCOME`, увеличивает recovery-required telemetry и не повторяется автоматически. Replay возвращает тот же `UNKNOWN_OUTCOME` без adapter.
- Package не выполняет recovery, rollback или compensation; оператор не должен интерпретировать classification как выполненное восстановление.

## Security и read-only

Публичный API не экспортирует adapter/store, не принимает adapter/runtime/registry injection и не предоставляет mutating CLI. Read-only CLI поддерживает только status/inspection/dry-run. Registry/service-set inspection не создают файлов. `real_execute()` не меняет durable store. Pre-admission deny удаляет claim и не создаёт receipt/budget usage. Telemetry различает simulated и real counters; real counters остаются нулевыми.

## Покрытие acceptance tests

- shadow: 1024 full admission evaluations, mixed allow/deny, adapter calls 0;
- rehearsal: 1000 isolated success/failure/UNKNOWN/post-gate scenarios, real effects 0;
- concurrency: 50 coordinators, 100 claim contenders, 100 duplicates, 100 reverse-order requests, 100 overlapping intents;
- negative matrix: 95 explicit deny cases, включая 75 service-set и forbidden operation/blast/control cases;
- performance: 5000 admission decisions и 10000 semantic-key calculations с bounded thresholds.

Эти тесты подтверждают текущую simulation boundary, но не заменяют future production safety certification.
