# Sprint 1.3.13 — Service Restart Canary Safety Document

## 1. Restart Authority Is Separate from Reload Authority

Restart authority (`HERMES_AUX_SERVICE_RESTART_CANARY`) is a narrow typed capability.
It does NOT inherit from reload authority. The following is FORBIDDEN:

```
if reload_allowed:
    restart_allowed = True  # ← NEVER
```

Restart requires its own:
- restart profile (validated)
- restart approval (single-use, bound)
- restart plan (immutable, TTL)
- restart budget (separate: 1 success / 2 attempts)
- restart circuit breaker
- restart execution gate (typed request only)

## 2. Exact Allowlist

The allowlist is STATIC with exactly ONE entry:

| Field | Value |
|-------|-------|
| service_id | `hermes-aux-canary` |
| unit_name | `hermes-aux-canary.service` |
| profile_version | 1 |
| expected_executable | `/home/hermes/.hermes/managed/canary-service/handler.py` |
| expected_user | `hermes` |
| restart_contract_version | 1 |

No glob, regex, prefix, env-only authority, or runtime-discovered authority.

## 3. Restart Profile Revalidation

Before a live restart, the candidate must satisfy:

- `service_class` = HERMES_AUXILIARY
- `criticality` = LOW
- `identity` = VERIFIED
- `graph` = HEALTHY
- `blast_radius` ≤ SERVICE
- `dependents` = 0
- `consumer` = NONE
- `restart_supported` = true
- quiescence contract proven
- startup contract proven
- health contract complete
- rollback/recovery contract proven

Otherwise: **DENY**.

## 4. Old PID Transition

After restart, old process identity (PID + start identity) must be GONE.
PID change alone is insufficient — PID reuse is possible, so comparison is
PID + start identity.

## 5. Quiescence

After stop phase:
- old process gone
- children gone
- cgroup old workload gone/acceptable
- ports released
- sockets transitioned
- no stale ownership

NOT_QUIESCENT → do NOT declare restart success.

## 6. Circuit Breaker

Opens immediately on:
- UNKNOWN_OUTCOME
- old PID survives unexpectedly
- orphan detected
- quiescence failure
- start timeout
- wrong new executable
- wrong new user/cgroup
- health failure
- rollback/recovery failure

Breaker open → further restart adapter=0.

## 7. Unknown Outcome — No Auto-Retry

If restart command times out or status is unavailable:
- Outcome = UNKNOWN_OUTCOME
- retry = 0
- Do NOT issue second restart
- Run reconciliation + identity check + manual review

## 8. Restart-as-Rollback — DENY

```
failed restart → restart again  # ← DENIED
```

Adapter second restart = 0. No automatic production rollback requiring
another restart.

## 9. Gateway P0

`hermes-gateway`:
- restart → SELF_CONTROL_FORBIDDEN
- reload → SELF_CONTROL_FORBIDDEN
- stop → SELF_CONTROL_FORBIDDEN
- start → SELF_CONTROL_FORBIDDEN
- kill → SELF_CONTROL_FORBIDDEN
- signal → SELF_CONTROL_FORBIDDEN

All adapter=0. The agent never mutates its own gateway process.

## 10. Stop/Start — Not Public

The restart executor may internally invoke the exact restart primitive,
but does NOT grant independent STOP or START authority.

Requests for STOP or START → OPERATION_DENIED, adapter=0.

## 11. Process Signals — Not Public

No public kill/pkill/signal API. The restart primitive is NOT implemented
through an arbitrary signal. Gateway process signals: FORBIDDEN.

## 12. Budget

For Sprint 1.3.13:
- `MAX_SUCCESSFUL_RESTARTS` = 1
- `MAX_TOTAL_RESTART_ATTEMPTS` = 2

After first successful live restart: budget prevents further live restart.

## 13. Kill-Switch

After live success:
- `HERMES_SERVICE_RESTART_CANARY_V2_ENABLED` = false
- Restart request → CANARY_DISABLED, adapter=0

## 14. Security

Scan of all module files, tests, receipts, events, health output:
- No env values
- No credentials
- No PAT
- No secret content
- **REAL_SECRET_FINDINGS = 0**

## 15. Database / Durability

Dedicated Hermes-owned durable restart store (file-backed, NOT state.db):
- `~/.hermes/managed/canary-service/restart-store/`
- Duplicate receipts = 0
- Orphan transactions = 0
- Active stale locks = 0

Production state.db is NOT mutated by this module.

## 16. Global Invariants

- `SYSTEM_CONTROL` = OFF
- Generic `SERVICE_CONTROL` = DENIED
- `production restart` = ≤1 (budget enforced)
- `production stop` = 0
- `production start` = 0
- `process signals` = 0
- `gateway mutation` = 0
