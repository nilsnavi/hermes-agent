# Sandbox Chaos Matrix 1.3.6

## Итог

Deterministic scenarios: **104**; PASS: **104**; FAIL: **0**.

Все destructive/process/service сценарии выполняются только в disposable sandbox roots. Gateway, production services, provider, scheduler, network и firewall не являются целями.

## Process death C1–C10

C1 kill before execute; C2 kill during partial file write; C3 kill immediately after atomic rename; C4 kill before verify; C5 kill during verify; C6 kill after verify; C7 kill during health; C8 kill before commit; C9 kill during rollback; C10 kill after resource restore before terminal rollback marker.

## Fault framework

55 `FaultPoint`; default-off. Runtime strings разрешены только через `ChaosController.from_runtime(..., test_mode=True)`. Production runtime не принимает произвольный chaos input.

## Матрица доказательств

| Scenario | Fault point | Expected | Actual | Adapter calls | Mutations | Manual review | Result |
|---|---|---|---|---:|---:|---:|---|
| `C1` | `BEFORE_EXECUTE` | `NOT_APPLIED` | `NOT_APPLIED` | 0 | 0 | no | **PASS** |
| `C2` | `MID_EXECUTE` | `UNKNOWN_OUTCOME` | `UNKNOWN_OUTCOME` | 0 | 0 | yes | **PASS** |
| `C3` | `AFTER_ATOMIC_RENAME` | `UNKNOWN_OUTCOME` | `UNKNOWN_OUTCOME` | 0 | 0 | yes | **PASS** |
| `C4` | `BEFORE_VERIFY` | `APPLIED_UNCOMMITTED` | `APPLIED_UNCOMMITTED` | 0 | 0 | no | **PASS** |
| `C5` | `MID_VERIFY` | `APPLIED_UNCOMMITTED` | `APPLIED_UNCOMMITTED` | 0 | 0 | no | **PASS** |
| `C6` | `AFTER_VERIFY` | `APPLIED_UNCOMMITTED` | `APPLIED_UNCOMMITTED` | 0 | 0 | no | **PASS** |
| `C7` | `MID_HEALTH` | `APPLIED_UNCOMMITTED` | `APPLIED_UNCOMMITTED` | 0 | 0 | no | **PASS** |
| `C8` | `BEFORE_COMMIT` | `APPLIED_UNCOMMITTED` | `APPLIED_UNCOMMITTED` | 0 | 0 | no | **PASS** |
| `C9` | `MID_ROLLBACK` | `UNKNOWN_OUTCOME` | `UNKNOWN_OUTCOME` | 0 | 0 | yes | **PASS** |
| `C10` | `AFTER_ROLLBACK` | `ROLLBACK_UNCOMMITTED` | `ROLLBACK_UNCOMMITTED` | 0 | 0 | yes | **PASS** |
| `P1` | `partial-temp-write` | `ROLLED_BACK` | `ROLLED_BACK` | 0 | 1 | no | **PASS** |
| `P2` | `missing-fsync` | `ROLLED_BACK` | `ROLLED_BACK` | 0 | 1 | no | **PASS** |
| `P3` | `missing-rename` | `ROLLED_BACK` | `ROLLED_BACK` | 0 | 1 | no | **PASS** |
| `P4` | `rename-complete-commit-missing` | `ROLLED_BACK` | `ROLLED_BACK` | 0 | 1 | no | **PASS** |
| `P5` | `original-unexpectedly-removed` | `ROLLED_BACK` | `ROLLED_BACK` | 0 | 1 | no | **PASS** |
| `P6` | `content-corrupted` | `ROLLED_BACK` | `ROLLED_BACK` | 0 | 1 | no | **PASS** |
| `P7` | `partial-chmod` | `ROLLED_BACK` | `ROLLED_BACK` | 0 | 1 | no | **PASS** |
| `P8` | `parent-changed` | `ROLLED_BACK` | `ROLLED_BACK` | 0 | 1 | no | **PASS** |
| `P9` | `inode-replaced` | `ROLLED_BACK` | `ROLLED_BACK` | 0 | 1 | no | **PASS** |
| `R1` | `snapshot-missing` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `R2` | `source-locked` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `R3` | `permission-restore` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `R4` | `disk-full` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `R5` | `destination-gone` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `R6` | `parent-drift` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `R7` | `symlink-swap` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `R8` | `service-refusal` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `R9` | `worker-death` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `R10` | `verify-io` | `MANUAL_REVIEW_REQUIRED` | `MANUAL_REVIEW_REQUIRED` | 0 | 0 | yes | **PASS** |
| `T-PREFLIGHT` | `PREFLIGHT` | `TIMEOUT` | `TIMEOUT` | 0 | 0 | no | **PASS** |
| `T-SNAPSHOT` | `SNAPSHOT` | `TIMEOUT` | `TIMEOUT` | 0 | 0 | no | **PASS** |
| `T-LOCK` | `LOCK` | `TIMEOUT` | `TIMEOUT` | 0 | 0 | no | **PASS** |
| `T-EXECUTE` | `EXECUTE` | `TIMEOUT` | `TIMEOUT` | 0 | 0 | no | **PASS** |
| `T-VERIFY` | `VERIFY` | `TIMEOUT` | `TIMEOUT` | 0 | 0 | no | **PASS** |
| `T-HEALTH` | `HEALTH` | `TIMEOUT` | `TIMEOUT` | 0 | 0 | no | **PASS** |
| `T-ROLLBACK` | `ROLLBACK` | `TIMEOUT` | `TIMEOUT` | 0 | 0 | no | **PASS** |
| `CON-DUP-50` | `duplicate` | `EXACTLY_ONCE` | `EXACTLY_ONCE` | 1 | 1 | no | **PASS** |
| `CON-SAME-20` | `same-resource` | `SERIALIZED` | `SERIALIZED` | 20 | 20 | no | **PASS** |
| `CON-DIFF-20` | `different-resources` | `PARALLEL` | `PARALLEL` | 20 | 20 | no | **PASS** |
| `CON-writer-vs-rollback` | `writer-vs-rollback` | `SERIALIZED` | `SERIALIZED` | 0 | 0 | no | **PASS** |
| `CON-verify-vs-writer` | `verify-vs-writer` | `STALE_VERIFY_REJECTED` | `STALE_VERIFY_REJECTED` | 0 | 0 | no | **PASS** |
| `CON-delete-vs-write` | `delete-vs-write` | `SERIALIZED` | `SERIALIZED` | 0 | 0 | no | **PASS** |
| `CON-rename-vs-chmod` | `rename-vs-chmod` | `SERIALIZED` | `SERIALIZED` | 0 | 0 | no | **PASS** |
| `SVC-pid-reuse` | `pid-reuse` | `SAFE` | `SAFE` | 0 | 0 | no | **PASS** |
| `SVC-unrelated-survival` | `unrelated-survival` | `SAFE` | `SAFE` | 0 | 0 | no | **PASS** |
| `SVC-identity-drift` | `identity-drift` | `SAFE` | `SAFE` | 0 | 0 | no | **PASS** |
| `SVC-process-group-reap` | `process-group-reap` | `SAFE` | `SAFE` | 0 | 0 | no | **PASS** |
| `SVC-health-timeout` | `health-timeout` | `SAFE` | `SAFE` | 0 | 0 | no | **PASS** |
| `SVC-production-block` | `production-block` | `SAFE` | `SAFE` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_PLAN` | `BEFORE_PLAN` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_PLAN` | `AFTER_PLAN` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_PREFLIGHT` | `BEFORE_PREFLIGHT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_PREFLIGHT` | `DURING_PREFLIGHT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_PREFLIGHT` | `AFTER_PREFLIGHT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_APPROVAL` | `BEFORE_APPROVAL` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_APPROVAL` | `AFTER_APPROVAL` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_SNAPSHOT` | `BEFORE_SNAPSHOT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_SNAPSHOT_CREATE` | `DURING_SNAPSHOT_CREATE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_SNAPSHOT_CONTENT` | `AFTER_SNAPSHOT_CONTENT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_SNAPSHOT_MANIFEST` | `AFTER_SNAPSHOT_MANIFEST` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_SNAPSHOT` | `AFTER_SNAPSHOT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_LOCK` | `BEFORE_LOCK` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_LOCK_ACQUIRE` | `DURING_LOCK_ACQUIRE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_LOCK` | `AFTER_LOCK` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_EXECUTION_RECEIPT` | `BEFORE_EXECUTION_RECEIPT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_EXECUTION_RECEIPT` | `AFTER_EXECUTION_RECEIPT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_EXECUTE` | `BEFORE_EXECUTE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_EXECUTE` | `DURING_EXECUTE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_EXECUTE` | `AFTER_EXECUTE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_EXECUTED_RECEIPT` | `BEFORE_EXECUTED_RECEIPT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_EXECUTED_RECEIPT` | `AFTER_EXECUTED_RECEIPT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_VERIFY` | `BEFORE_VERIFY` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_VERIFY` | `DURING_VERIFY` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_VERIFY` | `AFTER_VERIFY` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_VERIFIED_RECEIPT` | `BEFORE_VERIFIED_RECEIPT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_VERIFIED_RECEIPT` | `AFTER_VERIFIED_RECEIPT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_HEALTH` | `BEFORE_HEALTH` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_HEALTH` | `DURING_HEALTH` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_HEALTH` | `AFTER_HEALTH` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_COMMIT` | `BEFORE_COMMIT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_COMMIT_APPEND` | `DURING_COMMIT_APPEND` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_COMMIT_APPEND` | `AFTER_COMMIT_APPEND` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_COMMIT_FSYNC` | `BEFORE_COMMIT_FSYNC` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_COMMIT_FSYNC` | `AFTER_COMMIT_FSYNC` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_COMMIT` | `AFTER_COMMIT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_ROLLBACK` | `BEFORE_ROLLBACK` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_ROLLBACK` | `DURING_ROLLBACK` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_ROLLBACK_RESTORE` | `AFTER_ROLLBACK_RESTORE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_ROLLBACK_VERIFY` | `BEFORE_ROLLBACK_VERIFY` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_ROLLBACK_VERIFY` | `DURING_ROLLBACK_VERIFY` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_ROLLBACK_VERIFY` | `AFTER_ROLLBACK_VERIFY` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_ROLLBACK` | `AFTER_ROLLBACK` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_RECOVERY_SCAN` | `BEFORE_RECOVERY_SCAN` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_RECOVERY_SCAN` | `DURING_RECOVERY_SCAN` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_RECOVERY_SCAN` | `AFTER_RECOVERY_SCAN` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-BEFORE_RECONCILE` | `BEFORE_RECONCILE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-DURING_RECONCILE_READ` | `DURING_RECONCILE_READ` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-AFTER_RECONCILE` | `AFTER_RECONCILE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-JOURNAL_SHORT_WRITE` | `JOURNAL_SHORT_WRITE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-JOURNAL_FSYNC_FAILURE` | `JOURNAL_FSYNC_FAILURE` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-SNAPSHOT_CORRUPTION` | `SNAPSHOT_CORRUPTION` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-LOCK_OWNER_DEATH` | `LOCK_OWNER_DEATH` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-LOCK_TOCTOU` | `LOCK_TOCTOU` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |
| `FP-SERVICE_TIMEOUT` | `SERVICE_TIMEOUT` | `DETERMINISTIC_INJECTION` | `DETERMINISTIC_INJECTION` | 0 | 0 | no | **PASS** |

## Дополнительные регрессии

- Snapshot corruption: missing manifest/content, SHA mismatch, metadata corruption, wrong transaction/resource identity, truncation, cross-transaction reuse — fail-closed.
- Idempotency: lifecycle replay matrix; `EXECUTING`/`UNKNOWN_OUTCOME` never re-executes.
- TOCTOU/path: symlink, parent, inode and name-swap cases block before adapter or end in rollback/manual review.
- Permission/disk: ENOSPC, EACCES, EPERM, EROFS normalized to canonical taxonomy.
- Indirect system control: shell/python/script/nohup/env/setsid/service/kill/PID routes remain BLOCK with adapter calls 0.

## Live L1–L12

Отдельный subprocess с `HERMES_SANDBOX_MUTATION_V2_ENABLED=true` и `HERMES_SANDBOX_MUTATION_V2_MODE=sandbox`: **12/12 PASS**, `production_mutations=0`.
