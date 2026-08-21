# Sprint 1.3.13 — Single Auxiliary Service Restart Canary

**Status:** PASS — module built, 155/155 tests green, shadow 50 PASS, rehearsal 250 PASS, negative matrix 18/18 denied, single live restart committed.
**Live restart:** VERIFIED — exactly one restart of `hermes-aux-canary.service`; old identity `310030/12246227` gone, new identity `310281/12311741` verified, replay adapter=0, kill-switch ON.

## Capability

`HERMES_AUX_SERVICE_RESTART_CANARY` — narrow typed capability, SEPARATE from reload authority.
No implicit inheritance. Restart authority requires its own profile, approval, plan, budget,
breaker, execution gate.

## Selected Service

- **Unit:** `hermes-aux-canary.service`
- **Service ID:** `hermes-aux-canary`
- **Class:** HERMES_AUXILIARY
- **Criticality:** LOW
- **Blast radius:** SERVICE
- **Dependents:** 0
- **Consumer:** NONE
- **Executable:** `/home/hermes/.hermes/managed/canary-service/handler.py`
- **User:** hermes

## Module: `agent/service_restart_canary/`

### Files

| File | Purpose |
|------|---------|
| `__init__.py` | Architecture docstring + `__all__` |
| `models.py` | `ServiceRestartCanaryPlan`, `RestartApproval`, `RestartExecutionRequest`, enums |
| `flags.py` | `HERMES_SERVICE_RESTART_CANARY_V2_ENABLED` / `_MODE` (off/shadow/canary) |
| `allowlist.py` | Static exact single-entry allowlist (`hermes-aux-canary.service`) |
| `policy.py` | Fail-closed admission; denies all non-aux/non-low/non-service classes |
| `approval.py` | Single-use bound approval with drift/expiry invalidation |
| `budget.py` | max_success=1, max_attempts=2 (separate from reload budget) |
| `breaker.py` | Circuit breaker: opens on UNKNOWN_OUTCOME / old-PID-survives / orphan / etc. |
| `preflight.py` | Typed preflight: budget, breaker, identity, graph, blast, config, health, ports, orphans |
| `plan.py` | Immutable `ServiceRestartCanaryPlan` with TTL |
| `executor.py` | Typed `RestartExecutionRequest` ONLY; no raw command/shell/generic systemctl |
| `verify.py` | Old-identity-gone, quiescence, post-start identity, port, orphan checks |
| `stabilization.py` | Bounded health window T+0/2/5/10; all HEALTHY or no COMMIT |
| `recovery.py` | Durable-evidence-only recovery; restart-as-rollback HARD DENIED |
| `unknown_outcome.py` | No auto-retry; MANUAL_REVIEW for timeout/interruption |
| `idempotency.py` | Durable file-backed exactly-once; replay → DUPLICATE adapter=0 |
| `lock.py` | Durable cross-process per-service lock; same-service writers ≤1 |
| `gateway.py` | Any gateway op → SELF_CONTROL_FORBIDDEN adapter=0 |
| `negative_matrix.py` | 18 deny cases: unregistered, gateway, scheduler, provider, database, etc. |
| `shadow.py` | ≥50 shadow evaluations, 0 mutations, candidate correctness 100% |
| `rehearsal.py` | 250 chaos drills: 50 success + 20×9 + 10×2 = 250, violations=0 |
| `events.py` | Append-only RestartCanaryEventLog |
| `telemetry.py` | Thread-safe counters: restart_success/attempts/adapter_calls/etc. |
| `exceptions.py` | RestartCanaryError hierarchy |
| `cli.py` | Read-only CLI: status/inspect/eligibility/plan/shadow/rehearsal (no execute) |
| `manager.py` | Orchestrator: kill-switch → idem → admission → budget → breaker → approval → lock → execute → commit |

### Pipeline

```
RestartFoundation → RestartCanaryPolicy → RestartPlan
    → ExactRestartExecutor → Verify → Stabilization → Commit
```

### Deny Paths (adapter=0)

- gateway → SELF_CONTROL_FORBIDDEN
- unregistered → NOT_REGISTERED
- stop/start → OPERATION_DENIED
- kill/signal → OPERATION_DENIED
- replay/dup → DUPLICATE_ALREADY_COMMITTED
- generic systemctl → unavailable (no public API)

### Hard Gates

1. Kill-switch (ON by default; flag off = CANARY_DISABLED)
2. Budget (max_success=1, max_attempts=2)
3. Circuit breaker (opens on any safety violation)
4. Durable idempotency (file-backed exactly-once)
5. Durable per-service lock (cross-process, file-backed)
6. Single-use approval (bound to full contract, drift-invalidate)
7. TTL (expiry → invalid)

## Feature Flags

| Flag | Default | Description |
|------|---------|-------------|
| `HERMES_SERVICE_RESTART_CANARY_V2_ENABLED` | `false` | Master gate; flag NEVER grants authority |
| `HERMES_SERVICE_RESTART_CANARY_V2_MODE` | `off` | off / shadow / canary; unknown → off |

## Global Controls

- `SYSTEM_CONTROL` = **OFF**
- Generic `SERVICE_CONTROL` = **DENIED**
- Restart authority = narrow typed capability, NOT general service control

## Live Result

The brief's §37 hard approval gate was satisfied before execution. One restart was
committed. No second restart is authorized. The canary remains active/running as a
harmless test fixture:

`CANARY_SERVICE_LIFECYCLE=KEEP_RUNNING_AS_HARMLESS_TEST_FIXTURE`

Detailed sanitized evidence and runtime-store classification are recorded in
`docs/hermes-v2/restart-canary-baseline-consolidation-1.3.13.1.md`.

## Backup

- **Path:** `~/hermes-backup-sprint1.3.13-prechange-20260820-004547/`
- **SHA256SUMS:** 250/250 OK
- **state.db:** included (online backup)

## Test Results

- **Scoped (service_restart_canary):** 28 files, 155 tests passed, 0 failed
- **Targeted regression:** service_restart_foundation (212 tests) + reload + foundation — all PASS
- **Post-live canonical:** 3028 files; 32049 passed, 101 failed, 285 skipped; all failures classified unrelated/environmental, sprint module failures=0, NEW_REGRESSIONS=0.

## Lineage

- Baseline SHA: `20df1f1115ab5a04c8380ce2c34efa1422290d2d`
- Tag: `hermes-v2-restart-foundation-1.3.12`
- No merge/rebase upstream. No commit/push.
