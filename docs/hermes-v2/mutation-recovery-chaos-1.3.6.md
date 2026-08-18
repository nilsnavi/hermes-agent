# Sprint 1.3.6 — Mutation Recovery & Chaos Hardening

## Статус и область

Sprint 1.3.6 усиливает только `agent/sandbox_runtime/`. Production `SYSTEM_CONTROL` остаётся выключен. Production-конфигурация, провайдеры, scheduler, сеть, firewall и production-сервисы не являются допустимыми целями.

## Архитектура

Путь штатной sandbox-транзакции:

`plan → preflight → approval → snapshot → lock → execute → verify → health → commit`

Путь восстановления разделён на независимые read-only стадии:

`durable journal → incomplete scanner → reconciliation → disposition → manual review`

Scanner не вызывает adapter и не исправляет состояние. Reconciliation только сравнивает observed state с expected-before и expected-after. Возобновление, rollback и повтор mutation не являются поведением по умолчанию.

## Durable transaction contract

Durable запись связывает `transaction_id`, `run_id`, `step_id`, `request_id`, `idempotency_key`, operation/resource identity, preflight fingerprint, snapshot/approval references, execution/verification/health/rollback receipts и timestamps.

Commit marker допустим только при наличии:

- execution receipt;
- успешного verification receipt;
- успешного health receipt.

Нарушение инварианта не нормализуется в успех.

## UNKNOWN_OUTCOME

`EXECUTION_STARTED` без достоверного `EXECUTION_COMPLETED` означает `UNKNOWN_OUTCOME`.

Запрещено автоматически повторять mutation. Разрешённый путь:

`inspect actual resource → reconcile → verify → rollback либо manual review`.

## Safety-инварианты

- `BLOCK ⇒ adapter_calls=0`;
- `UNKNOWN_OUTCOME ⇒ retry_count=0`;
- `COMMITTED ⇒ verify=true ∧ health=true`;
- snapshot создаётся до mutation;
- cross-transaction snapshot reuse запрещён;
- same resource имеет не более одного active writer;
- production target не мутируется;
- риск после boundary/policy не уменьшается.

## Изоляция chaos

Chaos framework выключен по умолчанию, принимает deterministic fault points только в test/sandbox режиме и не принимает произвольный production input.

## Rollback

Rollback обязан валидировать authenticity snapshot до изменения ресурса. Повреждённый snapshot, ambiguous path/lock identity или невозможность доказать восстановление приводят к `MANUAL_REVIEW_REQUIRED`. Original error и rollback error сохраняются раздельно.

## Verification evidence

- Canonical sandbox scope: **341/341 PASS**, 29 files.
- Deterministic acceptance matrix: **104/104 PASS**, включая 55 `FaultPoint`, phase-specific C1–C10, R1–R10, 9 partial mutations, 7 timeouts, concurrency и service chaos.
- Policy/SBL/executor/equivalence regression: **512/512 PASS**, 33 files.
- Live sandbox drill L1–L12: **12/12 PASS**, `production_mutations=0`.
- Performance: recovery scan 1000 tx p95 **52.23 ms**; reconciliation p95 **0.00042 ms**; lock check p95 **0.0167 ms**.
- Security scan module + live recovery artifacts: **0 findings**.

## Активация

Единственная разрешённая конфигурация:

```text
HERMES_SANDBOX_MUTATION_V2_ENABLED=true
HERMES_SANDBOX_MUTATION_V2_MODE=sandbox
```

Предпочтителен отдельный subprocess. Gateway restart не требуется и не выполняется. Production/enforce mode отсутствует.
