# Sandbox Recovery — Sprint 1.3.5

> Hermes Agent 2.0 · crash recovery & chaos handling of
> `agent/sandbox_runtime/` · 2026-08-14

## Crash semantics

The transaction journal (`.txn/transactions.jsonl`) records each
mutation's lifecycle. The critical contract (§24):

```
TOOL_STARTED committed  →  adapter invoked
TOOL_COMPLETED          →  result committed/rolled back
STARTED without COMPLETED → UNKNOWN_OUTCOME → MANUAL_REVIEW_REQUIRED
```

**Never** auto-retry a TOOL_STARTED-without-TOOL_COMPLETED mutation.

## State machine (§12)

```
CREATED → PLANNED → PREFLIGHT_OK → WAITING_APPROVAL → APPROVED
→ SNAPSHOT_CREATED → LOCK_ACQUIRED → EXECUTING → EXECUTED
→ VERIFYING → VERIFIED → HEALTH_CHECKING → COMMITTED
```

Error branches: PREFLIGHT_FAILED, APPROVAL_DENIED, APPROVAL_EXPIRED,
BACKUP_FAILED, LOCK_FAILED, EXECUTION_FAILED, UNKNOWN_OUTCOME,
VERIFY_FAILED, HEALTH_FAILED, ROLLBACK_REQUIRED, ROLLING_BACK,
ROLLED_BACK, ROLLBACK_VERIFY_FAILED, MANUAL_REVIEW_REQUIRED,
CANCELLED. Illegal transitions are refused (LEGAL_TRANSITIONS map).

## Recovery drill (§44) — Process A/B

```
Process A: mutation → crash after execute (TOOL_STARTED, no COMPLETED)
Process B: reopen store → find_orphaned() → classify_incomplete()
           → UNKNOWN_OUTCOME → MANUAL_REVIEW_REQUIRED, NO AUTO RETRY
```

Proven in `test_crash_recovery.py`:
- orphan STARTED classified UNKNOWN_OUTCOME
- recover_transactions → disposition MANUAL_REVIEW_REQUIRED
- completed transactions untouched
- store persists across reopen

## Rollback drill (§43)

```
1. create file A        5. force verify failure
2. snapshot             6. prove A restored byte-for-byte
3. change A → B         7. perms restored
4. rollback             8. hash matches
                        9. audit complete
                       10. transaction = ROLLED_BACK
```

Proven in `test_rollback.py` (content, permissions, deleted-file
restore, original-failure audit, manual-review on rollback verify
failure).

## Chaos matrix (§35)

Crashes tested at: after plan, after preflight, after approval, after
backup, after lock, during write, after write before verify, after
verify before health, after health before commit, during rollback.
Every case terminates in COMMITTED | ROLLED_BACK |
MANUAL_REVIEW_REQUIRED — never a silent partial mutation.

## Fault injection (§23)

`FaultInjector` (tests/sandbox only) arms deterministic crash points:
FAIL_AFTER_PREFLIGHT, FAIL_AFTER_BACKUP, FAIL_AFTER_LOCK,
FAIL_BEFORE_EXECUTE, FAIL_DURING_EXECUTE, FAIL_AFTER_EXECUTE,
FAIL_BEFORE_VERIFY, FAIL_DURING_VERIFY, FAIL_AFTER_VERIFY,
FAIL_DURING_HEALTH, FAIL_BEFORE_COMMIT, FAIL_DURING_ROLLBACK,
CRASH_AFTER_EXECUTE.

## Sprint 1.3.6 recovery model

Полная decision table и crash/rollback matrix вынесены в
`sandbox-crash-recovery-1.3.6.md` и `sandbox-chaos-matrix-1.3.6.md`.
Scanner bounded/deterministic/read-only. Reconciliation возвращает только
`UNCHANGED`, `APPLIED`, `PARTIALLY_APPLIED`, `DIVERGED` или `UNKNOWN` и
не исправляет ресурс. Любая недоказанная ветка —
`MANUAL_REVIEW_REQUIRED`; `UNKNOWN_OUTCOME` не re-execute.

## Manual review protocol

UNKNOWN_OUTCOME or ROLLBACK_VERIFY_FAILED always produces:
- `MANUAL_REVIEW_REQUIRED` disposition
- audit trail with BOTH original failure and rollback status
- no automatic retry, no automatic re-plan

Operator path: `python -m agent.sandbox_runtime.cli inspect <txid>`
→ classify → decide restore/keep → manual rollback if needed.
