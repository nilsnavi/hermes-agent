# Capability approval hardening evidence

## Scope and baseline
Изолированный `hermes_core`; production tool execution/approval ownership не изменялись. Protected execution использует отдельный `invoke_protected` без boolean bypass.

## Runtime Observations
Проверены `model_tools.py`, `tools/registry.py`, `gateway/` и существующие tool tests: entrypoint и policy/approval wiring принадлежат runtime; exact argument mutation, revocation lifetime и policy version persistence — UNVERIFIED.

## Contracts
Grant binds identity, tool and canonical SHA-256 arguments. Approval is optional or bound to the same execution. `issued_at`/`expires_at` use explicit evaluation time; revocation is supplied as immutable evidence. JSON canonicalization rejects non-finite and unsupported values. Deny-before-execute is mandatory.

## Test Evidence

| Contract | Test | Expected | Actual | Result | Evidence | Known limitation |
|---|---|---|---|---|---|---|
| S1 | `test_s1_s2_s16_denied_before_execute` | no unauthorized call | pass | PASS | executor count 0 | isolated |
| S2 | same | approval absent denied | pass | PASS | — | — |
| S3 | `test_s3_authorized_once` | one call | pass | PASS | count 1 | — |
| S4 | `test_s4_to_s7_context_mismatch` | session denied | pass | PASS | parameterized | — |
| S5 | same | turn denied | pass | PASS | — | — |
| S6 | same | call denied | pass | PASS | — | — |
| S7 | same | tool denied | pass | PASS | — | — |
| S8 | `test_s8_to_s10_argument_binding` | changed args denied | pass | PASS | digest | — |
| S9 | same | equivalent args same | pass | PASS | sorted JSON | — |
| S10 | same | different args differ | pass | PASS | digest | — |
| S11 | `test_s11_s12_expired_revoked` | expired denied | pass | PASS | explicit time | — |
| S12 | same | revoked denied | pass | PASS | flag | no durable store |
| S13 | `test_s13_s14_approval_binding` | wrong approval denied | pass | PASS | identity binding | — |
| S14 | same | valid approval authorized | pass | PASS | — | — |
| S15 | `test_s15_no_approval_needed` | no fake approval | pass | PASS | — | — |
| S16 | `test_s1_s2_s16_denied_before_execute` | missing grant denied | pass | PASS | — | — |
| S17 | `test_s17_stable_reason` | stable reason code | pass | PASS | `missing_grant` | — |
| S18 | `test_s18_executor_cannot_bypass` | executor unreachable | pass | PASS | count 0 | — |
| S19 | `test_s19_provider_neutral_objects_only` | core objects only | pass | PASS | module assertion | no SDK |
| S20 | `test_s20_prior_contracts_unaffected` | prior suite green | pass | PASS | full suite | — |

Additional corrective tests cover principal binding, future-issued grants, legacy `approved=True` without structured authorization, boolean bypass absence, and NaN/Infinity/unsupported argument rejection.

## Isolation and readiness
No network, database, subprocess, sleeps, credentials, provider SDKs or production approval services. B4: `PARTIALLY_ADDRESSED`; runtime adapter mapping, durable revocation, approval lifetime and production classification remain gaps. Production migration remains **NO-GO**.
