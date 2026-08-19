# Service Restart Recovery — Sprint 1.3.12

Recovery and rollback planning for restart is fundamentally harder than for
reload. In 1.3.12 all recovery/rollback work is **analysis only**; there is no
production rollback and no production crash-recovery mutation.

## UNKNOWN_OUTCOME handling

Critical restart states:

| State | Policy |
|---|---|
| STOP_UNKNOWN | do NOT blindly start |
| START_UNKNOWN | do NOT restart again |
| any unknown | no auto-retry; require reconcile / manual review / safe recovery analysis |

Recovery decisions come from durable evidence only.

## Crash recovery

Deterministic scenarios (fake runtime only): crash after stop request, after
old PID exit, during quiescence, before start, after start request, after new
PID appears, before health, after health. Decision is `RECONCILE |
MANUAL_REVIEW | HALT` — never a blind start.

## Rollback strategies

```
RECONCILE_CURRENT_STATE
START_PREVIOUS_VERSION
RESTORE_CONFIG_THEN_START
OPERATOR_INTERVENTION
UNSUPPORTED
```

`plan_rollback()` returns `production_mutation: 0` in 1.3.12. No production
rollback is executed. If restart rollback is unproven, future autonomous
eligibility is DENY.

## RESTART-AS-ROLLBACK PROHIBITION

"if restart failed — restart again" is **auto-retry, not rollback**, and is
HARD DENIED. There is deliberately no `RESTART_SAME_VERSION` strategy.

## Circuit breaker (foundation, tests only)

Future triggers: UNKNOWN_OUTCOME, orphan detected, start health fail, rollback
failure, identity mismatch after start. In 1.3.12 the breaker is wired for
shadow/tests only — there is no real production restart to trip it.