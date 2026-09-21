# Migration controller hardening evidence

## Scope and isolation
Only isolated `hermes_core` domain contract, deterministic tests and documentation changed. No production runtime wiring.

## Runtime evidence
Exact inspected paths: `gateway/run.py`, `gateway/session.py`, `hermes_state.py`, `hermes_core/domain/`, `hermes_core/application/`, `hermes_core/ports/`, and the four architecture documents named in the contract doc. Ownership VERIFIED; migration graph, drain completion, failover and persistence adapter mapping UNVERIFIED.

## M1–M24

| Contract | Test | Expected | Actual | Result | Evidence | Limitation |
|---|---|---|---|---|---|---|
| M1 | `test_m1_initial_owner` | one owner | pass | PASS | test | isolated |
| M2 | `test_m2_candidate_distinct` | candidate distinct | pass | PASS | test | isolated |
| M3 | `test_m3_deterministic` | deterministic | pass | PASS | test | isolated |
| M4 | `test_m4_generation_once` | +1 | pass | PASS | test | isolated |
| M5 | `test_m5_conflict` | conflict | pass | PASS | test | isolated |
| M6 | `test_m6_conflict_unchanged` | unchanged | pass | PASS | test | isolated |
| M7 | `test_m7_illegal_jump` | reject | pass | PASS | test | isolated |
| M8 | `test_m8_reject_no_advance` | no advance | pass | PASS | test | isolated |
| M9 | `test_m9_no_dual_owner` | single authority | pass | PASS | test | isolated |
| M10 | `test_m10_shadow_no_transfer` | owner current | pass | PASS | test | isolated |
| M11 | `test_m11_kill_switch` | blocked | pass | PASS | test | isolated |
| M12 | `test_m12_kill_fenced` | fenced | pass | PASS | test | isolated |
| M13 | `test_m13_scope_invalid` | fail closed | pass | PASS | test | isolated |
| M14 | `test_m14_request_immutable` | frozen | pass | PASS | test | isolated |
| M15 | `test_m15_state_immutable` | frozen | pass | PASS | test | isolated |
| M16 | `test_m16_result_immutable` | frozen | pass | PASS | test | isolated |
| M17 | `test_m17_drain_distinct` | distinct | pass | PASS | test | isolated |
| M18 | `test_m18_cutover_drain_required` | blocked | pass | PASS | test | isolated |
| M19 | `test_m19_rollback_fenced` | conflict | pass | PASS | test | isolated |
| M20 | `test_m20_failover_distinct` | explicit FAILOVER_NOT_ALLOWED | pass | PASS | controller.failover | mapping unverified |
| M21 | `test_m21_noop` | NOOP | pass | PASS | test | isolated |
| M22 | `test_m22_audit_no_runtime_objects` | controller result carries audit | pass | PASS | TransitionResult.audit | isolated |
| M23 | `test_m23_prior_suite_marker` + full suite | compatibility | pass | PASS | 126 tests | — |
| M24 | `test_m24_runtime_untouched` + changed-file scope | no production wiring | pass | PASS | hermes_core/docs/tests only | filesystem scope evidence |

Additional corrective tests cover malformed requests, negative generation, stale kill switch and drain fencing. Full suite result is recorded below.

## Validation and readiness
No network, DB, subprocess, providers, tools, deliveries, sessions, secrets or wall-clock operations. `test_migration_controller_contract.py`: 29 passed; complete `tests/hermes_core`: 126 passed. Additional tests cover full ownership lifecycle, stale/current failover, drain scope/staleness/noop/invalid jump, and kill-switch noop. B6: `PARTIALLY_ADDRESSED`. Production migration: **NO-GO**.
