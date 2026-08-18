# Sandbox Crash Recovery 1.3.6

## Принцип

Process death не превращает недоказанный результат в успех и не разрешает повторную mutation. Источник истины — durable append-only journal и фактическое состояние sandbox-ресурса.

## Recovery decision table

| Durable evidence | `RecoveryDisposition` | Допустимое действие |
|---|---|---|
| Valid `COMMITTED`, `ROLLED_BACK`, `CANCELLED`, `DENIED` | `TERMINAL` | Только вернуть durable prior result; adapter не вызывается |
| `execution_started=true`, `execution_completed=false` | `MANUAL_REVIEW_REQUIRED` | `UNKNOWN_OUTCOME`; inspect/reconcile, никогда не re-execute |
| `LOCK_ACQUIRED` с валидным живым lock proof | `WAIT_FOR_LOCK` | Не освобождать lock и не мутировать ресурс |
| `EXECUTED` или `VERIFIED` с валидными receipts | `SAFE_TO_CONTINUE_VERIFY` | Только explicit verify/health recovery; execute не повторяется |
| `PLANNED`, `PREFLIGHT_OK`, `WAITING_APPROVAL`, `APPROVED`, `SNAPSHOT_CREATED` | `SAFE_TO_ROLLBACK` | Explicit cancel/rollback procedure; scanner сам ничего не делает |
| `PREFLIGHT_FAILED`, `APPROVAL_DENIED`, `APPROVAL_EXPIRED`, `BACKUP_FAILED`, `LOCK_FAILED`, `EXECUTION_FAILED`, `VERIFY_FAILED`, `HEALTH_FAILED`, `ROLLBACK_REQUIRED` | `SAFE_TO_ROLLBACK` | Только при trusted snapshot и explicit authorization |
| `CREATED`, `STARTED`, `EXECUTING`, `VERIFYING`, `HEALTH_CHECKING`, `ROLLING_BACK`, `UNKNOWN_OUTCOME`, invalid terminal evidence, неизвестное состояние | `MANUAL_REVIEW_REQUIRED` | Reconcile/read-only inspection; guessed success запрещён |

Reconciliation может предоставить дополнительное observed-state evidence, но не меняет durable disposition автоматически: explicit recovery procedure обязана заново проверить policy, boundary и authorization.

## Scanner

`scan_incomplete_transactions()`:

- bounded;
- deterministic;
- read-only;
- не вызывает adapter;
- не запускает rollback/resume;
- классифицирует неизвестное fail-closed.

## Reconciliation

Результаты:

- `UNCHANGED` — observed соответствует before;
- `APPLIED` — observed точно соответствует after;
- `PARTIALLY_APPLIED` — видна часть expected-after;
- `DIVERGED` — observed не совпадает ни с before, ни с after;
- `UNKNOWN` — состояние нельзя достоверно прочитать.

Reconciliation ничего не исправляет.

## Stale locks

Освобождение stale lock допустимо только при доказанных одновременно условиях:

1. owner dead по process identity, а не только PID;
2. transaction не active;
3. resource state reconciled;
4. transaction id, process nonce/start identity и resource identity совпадают.

Иначе: `LOCK_STATE_AMBIGUOUS → MANUAL_REVIEW_REQUIRED`.

## Manual review

Durable review item содержит только минимальные поля: review/transaction IDs, reason, resource, operation, observed/expected state, original/rollback errors, created_at. Secrets, raw payloads, prompts, arguments и environment values не сохраняются.
