# Sprint 1.5.7 regression and differential parity evidence

## Runtime paths inspected
Inspected `gateway/run.py`, `gateway/session.py`, `hermes_state.py`, `model_tools.py`, `tools/registry.py`, `agent/model_resolution.py`, `agent/turn_model.py`, `hermes_core/domain/`, `hermes_core/application/`, `hermes_core/ports/`, and the architecture documents listed in the canonical prompt. Runtime ownership is authoritative; unsupported claims are UNVERIFIED.

## G1–G7 regression matrix
| Group | Status | Evidence |
|---|---|---|
| G1 session lifecycle | PARTIAL | existing session contracts; runtime persistence parity unverified |
| G2 fencing/stale ownership | PARTIAL | CAS contract tests; runtime integration unverified |
| G3 persistence outcomes | PARTIAL | isolated CAS tests; production adapter unverified |
| G4 delivery recovery | PARTIAL | D tests; runtime reconciliation unverified |
| G5 capability/approval | PARTIAL | S tests; runtime mapping unverified |
| G6 routing/fallback | PARTIAL | R tests; production precedence unverified |
| G7 production isolation | VERIFIED | changed scope hermes_core/tests/docs only |

## DP1–DP24 matrix
| Scenario | Test | Classification | Result |
|---|---|---|---|
| DP1 | `test_dp01_session_initial_state`; legacy unavailable | UNVERIFIED | PASS (core executed) |
| DP2 | `test_dp02_successful_lease`; legacy unavailable | UNVERIFIED | PASS |
| DP3 | `test_dp03_competing_lease`; legacy unavailable | UNVERIFIED | PASS |
| DP4 | `test_dp04_valid_release`; legacy unavailable | UNVERIFIED | PASS |
| DP5 | `test_dp05_stale_release`; legacy unavailable | UNVERIFIED | PASS |
| DP6 | `test_dp06_valid_close`; legacy unavailable | UNVERIFIED | PASS |
| DP7 | `test_dp07_stale_close`; legacy unavailable | UNVERIFIED | PASS |
| DP8 | `test_dp08_generation_monotonicity`; legacy unavailable | UNVERIFIED | PASS |
| DP9 | `test_dp09_persistence_successful_mutation`; legacy unavailable | UNVERIFIED | PASS |
| DP10 | `test_dp10_stale_persistence_mutation`; legacy unavailable | UNVERIFIED | PASS |
| DP11 | `test_dp11_persistence_failure`; legacy unavailable | UNVERIFIED | PASS |
| DP12 | `test_dp12_delivery_success`; legacy unavailable | UNVERIFIED | PASS |
| DP13 | `test_dp13_delivery_failure`; legacy unavailable | UNVERIFIED | PASS |
| DP14 | `test_dp14_delivery_metadata`; legacy unavailable | UNVERIFIED | PASS |
| DP15 | `test_dp15_ambiguous_delivery`; legacy unavailable | UNVERIFIED | PASS |
| DP16 | `test_dp16_authorized_tool`; legacy unavailable | UNVERIFIED | PASS |
| DP17 | `test_dp17_unauthorized_tool`; legacy unavailable | UNVERIFIED | PASS |
| DP18 | `test_dp18_approval`; legacy unavailable | UNVERIFIED | PASS |
| DP19 | `test_dp19_routing_purpose`; legacy unavailable | UNVERIFIED | PASS |
| DP20 | `test_dp20_route_selection`; legacy unavailable | UNVERIFIED | PASS |
| DP21 | `test_dp21_fallback`; legacy unavailable | UNVERIFIED | PASS |
| DP22 | `test_dp22_credential_reference`; legacy unavailable | UNVERIFIED | PASS |
| DP23 | `test_dp23_migration_isolation`; no legacy controller | NOT_APPLICABLE | PASS |
| DP24 | `test_dp24_suite_reference`; external validation gate | UNVERIFIED | PASS — direct parity 26/26; full hermes_core 152/152; canonical 152/152, 0 failed |

## Totals and validation
MATCH: 0; INTENTIONAL_DELTA: 0; UNVERIFIED: 23; NOT_APPLICABLE: 1. Direct parity tests: 26 passed; complete `tests/hermes_core`: 152 passed. Core outcomes are derived from executed domain/service operations; test PASS is not parity MATCH. No network, credentials, provider/tool/delivery side effects or production DB access. R: PARTIAL. P: PARTIAL. B: PARTIAL. Production migration: **NO-GO**.
