# Доказательства lifecycle/recovery/rollback — Sprint 1.5.8

## Inspected paths

`hermes_core/domain/migration.py`; `hermes_core/application/session_service.py`; `hermes_core/domain/session.py`; `hermes_core/application/delivery_service.py`; `hermes_core/domain/delivery.py`; `hermes_core/ports/delivery.py`; `gateway/run.py`; `gateway/session.py`; `hermes_state.py`; `tests/hermes_core/test_migration_controller_contract.py`; `tests/hermes_core/test_session_persistence_hardening.py`; `tests/hermes_core/test_delivery_recovery_contract.py`; `tests/hermes_core/test_lifecycle_recovery_contract.py`.

## Lifecycle graph

`OFF -> SHADOW -> CANARY -> DRAINING -> CUTOVER`; rollback из CANARY/DRAINING/CUTOVER в ROLLBACK и затем OFF. Legacy authoritative до CUTOVER; CUTOVER устанавливает HERMES_CORE/LEGACY; rollback и OFF восстанавливают LEGACY/HERMES_CORE. Generation и scope fencing обязательны; CUTOVER требует DRAINED.

## LR1–LR24 matrix

| ID | Сценарий | Test/evidence | Status | Result/reason |
|---|---|---|---|---|
| LR1 | initial OFF/LEGACY | `test_lr1_initial_off_legacy` | EXECUTED | phase/owner/generation/drain проверены |
| LR2 | OFF→SHADOW | `test_lr2_off_to_shadow` | EXECUTED | APPLIED, LEGACY |
| LR3 | SHADOW→CANARY | `test_lr3_lr4_forward_phases` | EXECUTED | APPLIED, LEGACY |
| LR4 | CANARY→DRAINING | `test_lr3_lr4_forward_phases` | EXECUTED | APPLIED, LEGACY |
| LR5 | drain request | `test_lr5_lr6_drain_progression` | EXECUTED | DRAIN_REQUESTED, generation +1 |
| LR6 | drain completion | same | EXECUTED | DRAINED, generation +1 |
| LR7 | cutover pre-drain | `test_lr7_cutover_before_drain_preserves_state` | EXECUTED | DRAIN_REQUIRED, unchanged |
| LR8 | valid cutover | `test_lr8_lr9_cutover_transfers_authority` | EXECUTED | APPLIED |
| LR9 | cutover state | same | EXECUTED | HERMES_CORE owner, LEGACY candidate, DRAINED |
| LR10 | CUTOVER→ROLLBACK | `test_lr10_lr11_lr12_rollback_restores_legacy` | EXECUTED | APPLIED |
| LR11 | rollback owner | same | EXECUTED | LEGACY restored |
| LR12 | ROLLBACK→OFF | same | EXECUTED | OFF/LEGACY |
| LR13 | stale transition | `test_lr13_lr14_lr15_rejections_preserve_complete_state` | EXECUTED | CONFLICT, unchanged |
| LR14 | wrong scope | same | EXECUTED | REJECTED, unchanged |
| LR15 | illegal transition | same | EXECUTED | INVALID_TRANSITION, unchanged |
| LR16 | stale rollback | `test_lr16_lr17_stale_and_wrong_scope_rollback` | EXECUTED | CONFLICT |
| LR17 | wrong-scope rollback | same | EXECUTED | REJECTED |
| LR18 | failure atomicity | `test_lr18_failure_atomicity_for_drain_and_invalid_state` | EXECUTED | state equality preserved |
| LR19 | kill switch | `test_lr19_kill_switch_blocks_and_unblocks_forward_progression` | EXECUTED | APPLIED/NOOP/KILL_SWITCHED |
| LR20 | stale kill enable/disable | `test_lr20_stale_kill_enable_and_disable_preserve_state` | EXECUTED | CONFLICT, unchanged |
| LR21 | failover | `test_lr21_failover_is_fail_closed_and_audited` | EXECUTED | FAILOVER_NOT_ALLOWED |
| LR22 | session recovery | `test_lr22_session_recovery_is_real_failure_preservation` | EXECUTED | persistence failure preserves state |
| LR23 | delivery recovery | `test_lr23_delivery_unknown_ack_is_real` | EXECUTED | UNKNOWN_ACK |
| LR24 | full rehearsal | `test_lr24_full_rehearsal_trace` + `run_full_rollback_rehearsal` | EXECUTED | 8 applied trace points, monotonic generations |

## SR1–SR6 matrix

| ID | Сценарий | Test/evidence | Status | Result/reason |
|---|---|---|---|---|
| SR1 | acquire persistence failure | `test_sr1_acquire_persistence_failure` | EXECUTED | PERSISTENCE_ERROR, source/durable preserved |
| SR2 | stale CAS | `test_sr2_stale_cas_conflict` | EXECUTED | CONFLICT |
| SR3 | release persistence failure | `test_sr3_release_persistence_failure` | EXECUTED | lease preserved |
| SR4 | close persistence failure | `test_sr4_close_persistence_failure` | EXECUTED | non-closed preserved |
| SR5 | stale owner | `test_sr5_stale_owner_rejected` | EXECUTED | REJECTED; caller/durable preserved |
| SR6 | retry after recovery | no supported deterministic API found | UNVERIFIED | adapter/runtime recovery semantics unavailable |

## DR1–DR6 matrix

| ID | Сценарий | Test/evidence | Status | Result/reason |
|---|---|---|---|---|
| DR1 | confirmed success | `test_dr1_confirmed_success` | EXECUTED | SUCCESS/DELIVERED |
| DR2 | confirmed failure | `test_dr2_confirmed_failure` | EXECUTED | FAILURE/FAILED |
| DR3 | ambiguous transport | `test_dr3_transport_error_unknown_ack` | EXECUTED | DeliveryTransportError -> TRANSPORT_ERROR/UNKNOWN_ACK |
| DR4 | reconciliation | `test_dr4_explicit_reconciliation` | EXECUTED | explicit result transitions |
| DR5 | abandonment | `test_dr5_explicit_abandonment` | EXECUTED | ABANDONED |
| DR6 | unexpected exception | `test_dr6_runtime_error_propagates` | EXECUTED | RuntimeError propagates; ATTEMPTING remains |

## Rollback rehearsal trace

`run_full_rollback_rehearsal()` captures immutable observations after SHADOW, CANARY, DRAINING, drain request, drained, CUTOVER, ROLLBACK and OFF. All eight operations are APPLIED with generations 1..8. Ownership is LEGACY through drain, HERMES_CORE/LEGACY at CUTOVER, then LEGACY/HERMES_CORE at ROLLBACK and OFF.

## Kill-switch and failover evidence

Kill switch enable/disable is fenced and idempotent; blocked forward migration preserves state. Failover checks generation first, then returns deterministic `FAILOVER_NOT_ALLOWED/failover_unverified` without mutation and with audit evidence.

## Validation

Final cleanup tree rerun: 2026-09-22, Windows / Python 3.14. Direct runs completed outside the sandbox to access installed pytest; the initial sandbox attempt could not import pytest. Both successful direct runs reported a cache-write warning (WinError 183). All four validation commands completed successfully.

- `python -m pytest tests/hermes_core/test_lifecycle_recovery_contract.py --confcutdir=tests/hermes_core -q`: 30 passed, 1 warning (PytestCacheWarning).
- `python -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q`: 182 passed, 1 warning (PytestCacheWarning).
- `python -m compileall hermes_core`: completed successfully.
- canonical `scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core`: 11 files, 182 passed, 0 failed; no retries reported.

## Remaining gaps and readiness impact

Operational recovery, SR6 retry semantics, durable audit persistence and adapter/runtime ownership execution are UNVERIFIED. L readiness = PARTIAL; B readiness = PARTIAL. Core contract evidence does not authorize migration.

## Production isolation

No production runtime, adapters, traffic switching, network calls or production DB were changed. Production migration remains NO-GO.
