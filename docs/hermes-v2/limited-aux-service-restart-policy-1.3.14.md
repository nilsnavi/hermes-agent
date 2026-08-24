# Sprint 1.3.14 — Limited Auxiliary Service Restart Policy

**Status:** hardening closeout in certification; no production restart/reload performed.

## Authority boundary

The policy supports a static immutable registry architecture with
`MAX_REGISTERED_RESTART_SERVICES=3`, but production authority remains limited to
profiles that are separately proven. Current live registry contains exactly one entry:

- service ID: `hermes-aux-canary`
- unit: `hermes-aux-canary.service`
- profile version: `1`

Runtime discovery is diagnostic evidence only and never grants authority.

Global invariants remain:

- `SYSTEM_CONTROL=OFF`
- generic `SERVICE_CONTROL=DENIED`
- public stop/start: denied
- process signal API: denied
- gateway self-control: forbidden
- kill-switch: ON
- live multi-service concurrency: disabled

## Architecture

`RestartFoundation → LimitedRestartRuntime (sole coordinator) → immutable registry/admission → atomic semantic claim → live-owner lock → duplicate recheck → approval → budget reservation → breaker → pre-execution revalidation → one-shot internal grant → non-authoritative BoundedRestartExecutor → ADAPTER_SUCCEEDED → transition/identity/config/graph/health verification → stabilization → coordinator-owned COMMITTED`

Components:

- `LimitedRestartPolicy`
- `RestartProfileRegistry`
- `RestartAdmission`
- `RestartConsumerPolicy`
- `RestartConcurrencyPolicy`
- `RestartApprovalPolicy` / `DurableApprovalStore`
- `HardenedServiceLock`
- `RestartBudget` / `DurableHourlyBudgets`
- `RestartCircuitBreaker` / `DurableCircuitBreaker`
- `DurableIdempotencyStore`
- `BoundedRestartExecutor`
- `LimitedRestartRuntime`
- `SystemClock` / `ControlledClock`

## Strict admission precedence

The policy implements the exact 20-step fail-closed order:

1. self-control
2. registry membership
3. service class
4. identity
5. profile version
6. graph
7. consumer
8. dependency
9. blast
10. pre-health
11. config
12. quiescence
13. startup
14. recovery
15. risk
16. approval
17. budget
18. breaker
19. lock
20. rollout flag

Unknown values fail closed. Risk and blast radius cannot be reduced by the policy.

## Consumer and blast policies

Allowed consumers: `NONE`, `PASSIVE`, `NON_CRITICAL`.

Denied consumers: `ACTIVE`, `CRITICAL`, `UNKNOWN`.

Allowed blast radius: `RESOURCE`, `SERVICE`.

Denied blast radius: `MULTI_SERVICE`, `HOST`, `NETWORK`, `UNKNOWN`.

Dynamic dependency growth produces a dependency denial/revalidation; it never lowers risk.

## Durable safety controls

### Idempotency

Semantic key: operation + service ID + profile version + explicit intent + baseline/config/
identity evidence. `CLAIMED` is acquired atomically before approval or budget consumption via
an OS file lock, atomic rename and fsync. After service-lock acquisition, runtime performs a
mandatory duplicate recheck. A committed cross-process replay returns the prior `COMMITTED`
result with `replayed=True`, `adapter_calls=0`; contenders never consume a second approval or
budget reservation.

`UNKNOWN_OUTCOME` is never retried automatically.

Every durable JSON store fails closed on unreadable, malformed or non-object state. Corruption
is never interpreted as an empty budget, closed breaker, absent lock or unclaimed intent.
Non-finite timestamps (`NaN`, positive/negative infinity and booleans) are rejected at public
temporal boundaries, and durable JSON serialization uses `allow_nan=False`.

### Lock

The per-service durable lock validates service + transaction + owner PID + process-start
identity + nonce + host + lease deadline + heartbeat/version. Lease expiry alone never permits
takeover: the owner must be proven dead/reused, durable transaction evidence must be inactive,
and safe recovery must allow takeover. Live and unknown owners fail closed. Renewal requires an
exact transaction/PID/start/nonce match. Same-service active writers never exceed one. Live multi-service concurrency remains
disabled; the policy class only permits future concurrency when explicitly enabled and graphs
do not intersect.

### Trusted clock

Production authority decisions accept no caller `now`. `SystemClock.monotonic()` controls
approval/plan TTL, lock lease, budget window, breaker cooldown and grant expiry; wall time is
audit metadata only. Durable roots bind the monotonic provenance to the current boot/clock and
fail closed after provenance change. Tests use construction-time `ControlledClock` injection.

### Budget

Rolling one-hour durable ceilings:

- per service: max attempts `2`, max successes `1`;
- global: max attempts `4`, max successes `2`.

Attempt and success receipts are separate. A service that has consumed its success cap cannot
reserve another restart attempt.

### Circuit breaker

Per-service breaker opens on execution/unknown/identity/quiescence/orphan/start/health/recovery
failure evidence. Open breaker returns `BREAKER_OPEN`, adapter `0`.

### Approval

`ApprovalContract` is immutable, single-use and bound to:

- service/profile/transaction;
- old process identity;
- graph and consumer state;
- config and health digests;
- risk and blast;
- quiescence/startup/recovery contracts;
- budget and breaker snapshots;
- plan hash;
- baseline SHA;
- TTL.

At execution, every binding is compared with the corresponding admission/runtime evidence,
not merely with the stored approval copy. `None`, empty bindings, drift, expiry and reuse fail
closed before any adapter call.

## Executor hardening

`BoundedRestartExecutor` is not exported from the package API and is a non-authoritative adapter
primitive. It accepts only:

`RestartExecutionRequest(service_id, profile_version, transaction_id)`

Execution also requires an exact one-shot internal grant issued by `LimitedRestartRuntime` only
after claim/lock/approval/budget/breaker/revalidation gates. The grant is bound to transaction,
service/profile/unit/operation/plan/approval/identity/graph/config/risk/blast/reservation/lock
nonce and monotonic expiry. Missing, fake, copied, expired, drifted or replayed grants deny with
zero adapter calls. The caller cannot provide a command, raw unit, arbitrary arguments or shell string. The registry
instance is non-replaceable and authority resolution uses a module-private canonical mapping,
not the replaceable compatibility class attribute. The executor accepts only the exact built-in
registry type and canonical profile. Registry resolution produces the exact unit. Execution uses
fixed argv:

`["systemctl", "--user", "restart", "hermes-aux-canary.service"]`

Properties: `subprocess.run`, `shell=False`, bounded timeout, captured bounded output,
structured adapter-level outcome (`ADAPTER_SUCCEEDED`, `ADAPTER_FAILED`,
`ADAPTER_UNKNOWN_OUTCOME`). It never returns `COMMITTED`; `os.system` is not used.

The adapter's zero exit code is not a commit. `LimitedRestartRuntime` requires an injected
post-restart verifier and commits only when expected transition, post-identity, config/graph
invariants, health, stabilization, lock ownership, budget reservation and approval/plan binding
all remain valid and no forbidden side effect/unknown outcome exists. Public durable-store APIs
cannot forge `COMMITTED`. A missing verifier returns `VERIFIER_REQUIRED` with adapter `0`;
post-verification failure persists a non-committed outcome and opens the breaker without retry.

Default construction has kill-switch ON and rollout disabled, so it cannot mutate production.

## Second-service discovery

A read-only survey inspected active user services. No second service had a fully proven restart
profile, quiescence/startup/health/recovery contracts and acceptable consumer risk.

- `SECOND_LIVE_SERVICE=SKIPPED`
- `reason=NO_ELIGIBLE_SECOND_AUXILIARY_SERVICE`

No production service was fabricated and the registry was not expanded.

## Shadow study

- evaluations: `112`
- correctness: `112/112 = 100%`
- mutations: `0`
- subprocess calls: `0`

All required families were exercised eight times each: registered, unregistered auxiliary,
gateway, scheduler, provider, unknown, stale graph, wrong identity, active consumer,
multi-service blast, bad health, expired approval, exhausted budget and open breaker.

## Rehearsal

The composed `LimitedRestartRuntime` is exercised end-to-end with fake subprocess I/O for every
mutating path. Concurrency uses two real threads contending for the same durable lock; stale,
PID-reuse and orphan cases enter through runtime lock acquisition; duplicate, unknown, breaker,
budget and post-health paths include their idempotency/accounting interactions:

- success: 50
- duplicate: 20
- concurrent conflict: 20
- stale lock: 20
- PID reuse: 20
- owner death/orphan: 20
- critical consumer: 20
- graph drift: 20
- health failure: 20
- `UNKNOWN_OUTCOME`: 10
- breaker open: 10
- budget exceeded: 10

Total: `240`; violations: `0`; real mutations: `0`; fake subprocess calls: `180`.

Expired-but-live lock scenarios now deny before adapter, accounting for the reduction from the
pre-hardening fake-call count while preserving all 240 scenario evaluations.

## Live read-only validation

Current `hermes-aux-canary.service` admission result:

- `ALLOW_EXACT_REGISTERED_PROFILE`
- execution result with production defaults: `KILL_SWITCH_ACTIVE`
- adapter calls: `0`

Gateway restart/reload/stop/start/kill/signal all return `SELF_CONTROL_FORBIDDEN`.
Public stop/start/kill/signal all return `OPERATION_DENIED`.

## Backup

Pre-change backup:

`~/hermes-backup-sprint1.3.14-prechange-20260821-130619`

`SHA256SUMS: 882/882 OK`; online `state.db` backup integrity: OK.

## Targeted regression

Final canonical targeted scope after source/docs/codemap changes:

- files: `103`
- tests passed: `910`
- failures: `0`
- `TEST_RUNNER_EXIT_CODE=0`

Covered: `service_restart_policy`, restart canary/foundation, reload policy/canary,
service foundation, production policy/canary, sandbox runtime and runner exit contract.

## Clean snapshot

An isolated HEAD archive overlaid only with the authoritative Sprint source set produced:

- `IMPORT_OK`
- `COMPILE_OK`
- 56 files / 394 tests passed / 0 failed
- runtime state files in snapshot: `0`

The snapshot does not depend on live PID, live receipts, locks, budgets, breaker state or DB.

## Fresh full canonical

- files: `3033`
- passed: `32094`
- failed: `111`
- skipped: `285`
- duration: `1040.3s`
- runner exit: `1` (expected fail-red environment)

Exact comparison with certified Sprint 1.3.13.1:

- new failing nodeids: `1` unrelated flaky PTY surrogateescape test; canonical retry PASS and
  isolated rerun PASS `3/3`
- resolved failing nodeids: `4`
- new collection errors: `0`
- resolved collection errors: `0`
- new failing nodeids attributable to Sprint 1.3.14: `0`
- `NEW_REGRESSIONS=0`

Machine-readable evidence:
`docs/hermes-v2/limited-aux-service-restart-policy-canonical-delta-1.3.14.json`.

## Independent security/logic review

The initial independent review returned FAIL and its approval, post-verification, durable-state,
clock-drift, registry and rehearsal findings were fixed. Two follow-up bypass findings (class
registry rebind and non-finite temporal values) were also fixed with regression tests.

Final independent read-only review: `PASS`; blocking findings: `0`; policy tests: `55 passed`.
The reviewer reproduced registry class rebind and `True`/`NaN`/`+Inf`/`-Inf` probes: all were
denied before adapter execution, canonical authority remained unchanged, adapter calls were `0`.

## Database read-only check

Production `state.db` was opened with SQLite `mode=ro`: `PRAGMA quick_check=ok` and
`PRAGMA foreign_key_check` returned zero rows. No database mutation was performed.

## Manifest policy

Prepare only; do not commit or push during Sprint 1.3.14.

Allowed source manifest:

- `agent/service_restart_policy/**`
- `tests/service_restart_policy/**`
- `docs/hermes-v2/limited-aux-service-restart-policy-1.3.14.md`
- `docs/hermes-v2/limited-aux-service-restart-policy-canonical-delta-1.3.14.json`
- `docs/codemap/codemap.json`
- `docs/codemap/codemap.html`
- `docs/codemap/codemap.lock`

Runtime receipts, locks, budgets, breaker state, PID state, logs, DB files, credentials and
secrets are excluded.
