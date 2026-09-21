# Delivery recovery contract

Production gateway delivery remains authoritative and is not modified. The isolated core models `PENDING`, `ATTEMPTING`, `DELIVERED`, `FAILED`, `UNKNOWN_ACK`, and terminal `ABANDONED`.

| Crash / failure point | External side effect possible? | Local evidence | Safe classification | Automatic retry safe? | Required future mechanism |
|---|---|---|---|---|---|
| before send | no | pending | PENDING | yes, by policy | attempt identity |
| request before payload transmission | unlikely/unknown | transport error | UNKNOWN_ACK unless adapter proves no send | no | provider evidence |
| after payload transmission before response | yes | no confirmed ACK | UNKNOWN_ACK | no | idempotency/reconciliation |
| remote success before local persistence | yes | external response only | UNKNOWN_ACK until durable | no | external ID + durable ledger |
| after local persistence | yes | confirmed local result | DELIVERED/FAILED | policy-owned | durable attempt record |
| crash while ATTEMPTING | possible | attempting marker | UNKNOWN_ACK | no | recovery scan and provider reconciliation |
| recovery of UNKNOWN_ACK | already possible | adapter evidence | DELIVERED, FAILED, or ABANDONED | only after evidence | provider reconciliation/manual decision |

Retry policy belongs to application/orchestration, not transport adapters. Missing local ACK is never proof that no external side effect occurred. Future adapters may use idempotency keys, provider message IDs, reconciliation APIs, durable attempt IDs, or deduplication records.

Legal recovery transitions are `PENDING → ATTEMPTING`, `ATTEMPTING → DELIVERED/FAILED/UNKNOWN_ACK`, and `UNKNOWN_ACK → DELIVERED/FAILED/ABANDONED`. Terminal states cannot be rewritten. Attempt identity/count beyond the current counter remains future adapter/application metadata.
