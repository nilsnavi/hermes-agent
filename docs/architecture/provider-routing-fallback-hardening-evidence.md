# Provider routing fallback hardening evidence

## Scope
Изолированный core; provider clients, credentials and runtime ownership unchanged.

## Runtime Observations
`hermes_core/application/provider_router.py`, `hermes_core/ports/providers.py`, `hermes_core/domain/routing.py`, `agent/model_resolution.py`, `agent/turn_model.py`, and `gateway/session.py` were inspected. Provider resolution is runtime-owned (VERIFIED); precedence, credential pools/recovery, retry ownership, prompt-cache affinity and profile/session precedence are PARTIAL/UNVERIFIED. No repository evidence proves a universal transient/rate fallback mapping, so the core default policy is deny-all.

## Contracts
Immutable candidates/plans sort deterministically. Failure classes carry reason and opaque reference. Only configured candidates can be selected; denied fallback and exhaustion are explicit.

## Test Evidence

| Contract | Test | Expected | Actual | Result | Evidence | Known limitation |
|---|---|---|---|---|---|---|
| R1 | `test_r1_r8_deterministic_order` | same first | pass | PASS | plan | fake |
| R2 | `test_r2_r3_no_secrets_opaque` | no secret | pass | PASS | repr | fake |
| R3 | same | opaque ref | pass | PASS | ref | — |
| R4 | `test_r4_purpose_distinct` | purpose retained | pass | PASS | enum | mapping unverified |
| R5 | `test_r5_precedence` | higher precedence first | pass | PASS | rank | runtime order unverified |
| R6 | `test_r6_r7_fallback_legal` | no immediate reselection | pass | PASS | remaining | — |
| R7 | same | configured only | pass | PASS | plan | — |
| R8 | `test_r1_r8_deterministic_order` | stable ordering | pass | PASS | sorted tuple | — |
| R9 | `test_r9_fallback_allowed_advances` | advance | pass | PASS | explicit validated policy | — |
| R10 | `test_r10_fallback_denied_stops` | stop | pass | PASS | status | — |
| R11 | `test_r11_exhaustion` | terminal exhausted | pass | PASS | status | — |
| R12 | `test_r12_missing_candidates` | explicit NO_ROUTE | pass | PASS | `select()` result | — |
| R13 | `test_r13_retry_distinct` | no retry loop | pass | PASS | evidence flag | runtime owner |
| R14 | `test_r14_provider_exception_not_modelled` | no SDK exception | pass | PASS | enum | — |
| R15 | `test_r15_r16_credential_reference_only` | no secret | pass | PASS | opaque ref | — |
| R16 | same | unavailable representable | pass | PASS | failure class | — |
| R17 | `test_r17_immutable` | immutable | pass | PASS | mutation reject | — |
| R18 | `test_r18_cache_unverified` | explicit gap | pass | PASS | purpose distinction | cache runtime |
| R19 | `test_r19_c4_compat` | C4 values | pass | PASS | enum | — |
| R20 | `test_r20_prior_domains_exist` | prior contracts unaffected | pass | PASS | suite | — |

## Isolation and readiness
No network, database, credentials, subprocess, sleeps, SDKs or production adapters. B5: `PARTIALLY_ADDRESSED`; production migration **NO-GO**.

Corrective tests additionally cover forward A→B→C progression, no cycles/backtracking, evidence/failed-candidate mismatch, external candidates, mixed purposes, duplicate logical routes, malformed candidates, denied AUTHENTICATION/INVALID_REQUEST/UNKNOWN fallback, malformed evidence/result objects, and explicit empty-plan selection. Complete isolated suite result: 97 passed.
