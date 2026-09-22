# Контракт lifecycle/recovery/rollback

## Границы
Изолированный `MigrationController` является control-plane контрактом. Он не переключает production traffic, не вызывает провайдеры, инструменты или delivery, не пишет production DB и не подключён к runtime. Production migration остаётся **NO-GO**.

## Граф и ownership

`OFF -> SHADOW -> CANARY -> DRAINING -> CUTOVER`; из `CANARY`, `DRAINING` и `CUTOVER` разрешён явный `ROLLBACK`, затем `ROLLBACK -> OFF`. SHADOW, CANARY и DRAINING сохраняют `LEGACY` как authoritative owner. CUTOVER разрешён только при `DRAINED` и устанавливает `owner=HERMES_CORE`, `candidate_owner=LEGACY`. ROLLBACK и OFF восстанавливают `owner=LEGACY`, `candidate_owner=HERMES_CORE`; owner и candidate никогда не совпадают.

## Fencing и drain

Каждая мутация содержит expected generation и scope. Несовпадение даёт `CONFLICT` без изменения состояния; несовпадение scope даёт `REJECTED`. Успешная мутация увеличивает generation ровно на один. Drain проходит `NOT_DRAINING -> DRAIN_REQUESTED -> DRAINED`; повторение даёт `NOOP`, недопустимый скачок отклоняется. CUTOVER до DRAINED возвращает `DRAIN_REQUIRED`.

## Rollback, kill switch и failover

Rollback — control-plane восстановление LEGACY ownership, без внешней отмены traffic. Kill switch generation-fenced, повторная установка — NOOP и блокирует forward transitions. `failover()` представлен отдельным API и результатом, но runtime semantics не подтверждены: актуальная операция возвращает `FAILOVER_NOT_ALLOWED/failover_unverified` и не меняет state.

## Recovery boundaries

Session CAS/persistence failures preserve caller and durable source state; delivery `UNKNOWN_ACK` требует explicit reconciliation или abandonment и не считается безопасным для автоматического retry. Operational recovery, adapters, durable audit storage и production ownership execution остаются UNVERIFIED/adapter-owned.

## Audit и изоляция

APPLIED, CONFLICT, REJECTED/INVALID_TRANSITION, KILL_SWITCHED и FAILOVER_NOT_ALLOWED возвращают immutable AuditEvent с transition id, generations, phases, owners, status и reason. Tests используют только in-memory fakes; production runtime untouched. Readiness: L/B — PARTIAL; production migration — NO-GO.
