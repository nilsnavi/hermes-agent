# Sprint 1.3.13 — Service Restart Canary Operator Runbook

## Overview

This runbook describes the procedure for performing the ONE authorized controlled
restart of `hermes-aux-canary.service` via the Sprint 1.3.13 restart canary.

## Prerequisites

1. Sprint 1.3.13 module built and tests green (155/155 scoped).
2. Shadow phase PASS (50 evaluations, 0 mutations).
3. Fake rehearsal PASS (250 drills, 0 violations).
4. Negative matrix PASS (18/18 denied).
5. Feature flags OFF by default.
6. Kill-switch ON by default.

## CLI Status Check (read-only)

```bash
cd ~/.hermes/hermes-agent-sprint137
~/.hermes/hermes-agent/venv/bin/python -m agent.service_restart_canary.cli status
~/.hermes/hermes-agent/venv/bin/python -m agent.service_restart_canary.cli inspect
~/.hermes/hermes-agent/venv/bin/python -m agent.service_restart_canary.cli eligibility
~/.hermes/hermes-agent/venv/bin/python -m agent.service_restart_canary.cli plan
~/.hermes/hermes-agent/venv/bin/python -m agent.service_restart_canary.cli shadow
~/.hermes/hermes-agent/venv/bin/python -m agent.service_restart_canary.cli rehearsal
```

## Live Restart Procedure

> Historical procedure: the one approved Sprint 1.3.13 live restart has already
> completed successfully. The kill-switch is ON and the success budget is exhausted.
> Do not execute this procedure again. Any later cleanup or mutation requires a
> separately approved operation.

### STOP — Explicit Approval Required

Per brief §37, after implementation + tests + shadow + rehearsal, the operator
must explicitly reply:

> **"одобряю live restart"**

or equivalent. This is a HARD GATE. No live restart without it.

### Before Live Restart

1. Capture gateway baseline:
   ```bash
   systemctl --user show hermes-gateway.service \
     -p MainPID -p NRestarts -p ActiveState -p SubState -p ExecMainStatus
   ```

2. Capture canary service state:
   ```bash
   systemctl --user show hermes-aux-canary.service \
     -p MainPID -p ActiveState -p SubState -p ExecMainStatus
   ```

3. Verify canary service exists and is the expected unit:
   ```bash
   systemctl --user list-unit-files hermes-aux-canary.service
   ```

4. Verify state.db integrity (read-only):
   ```bash
   ~/.hermes/hermes-agent/venv/bin/python -c "
   import sqlite3, os
   db = sqlite3.connect('file:%s?mode=ro' %
     os.path.expanduser('~/.hermes/state.db'), uri=True)
   print('quick_check:', db.execute('PRAGMA quick_check').fetchone()[0])
   print('fk_check:', len(db.execute('PRAGMA foreign_key_check').fetchall()))
   db.close()
   "
   ```

### Execution

After explicit approval, the live restart is executed via the typed
`RestartCanaryManager` which:

1. Checks kill-switch (must be OFF for canary mode)
2. Checks idempotency (no duplicate)
3. Runs admission (negative matrix)
4. Checks budget (1 success / 2 attempts)
5. Checks circuit breaker (must be CLOSED)
6. Validates single-use approval
7. Acquires durable per-service lock
8. Executes exactly ONE restart via typed `RestartExecutionRequest`
9. Verifies old identity gone, quiescence, new identity, ports
10. Runs stabilization health (T+0/2/5/10)
11. Commits (or fails without commit)

The actual restart primitive (inside the executor only):
```bash
systemctl --user restart hermes-aux-canary.service
```

**After first successful live restart, the canary auto-disables (kill-switch).**

### After Live Restart

1. Verify gateway unchanged:
   ```bash
   systemctl --user show hermes-gateway.service \
     -p MainPID -p NRestarts -p ActiveState -p SubState -p ExecMainStatus
   ```
   MainPID may differ (OS restarts), but NRestarts must be 0 (no systemd-revival).

2. Verify canary service:
   ```bash
   systemctl --user show hermes-aux-canary.service \
     -p MainPID -p ActiveState -p SubState -p ExecMainStatus
   ```

3. Verify state.db unchanged (read-only quick_check).

4. Replay test: re-issue same intent → expect DUPLICATE_ALREADY_COMMITTED, adapter=0.

5. Kill-switch verification: canary flag OFF → restart request → CANARY_DISABLED, adapter=0.

## Rollback Policy

Restart rollback is conservative:
- If restart succeeded but health fails: do NOT simply restart again.
- Allowed automatic recovery only if separately proven safe AND pre-authorized.
- Otherwise: MANUAL_REVIEW_REQUIRED.
- **Restart-as-rollback is HARD DENIED.**

## Recovery

Recovery decisions from durable evidence only:
- RECONCILE_RUNNING_HEALTHY — new process healthy, reconcile state
- RECONCILE_STOPPED — service stopped, investigate
- MANUAL_REVIEW — ambiguous, human investigation needed
- HALT — old PID survived or unsafe state

No blind restart. No automatic second restart.

## Feature Flag Rollback

To disable the canary (if needed):
```bash
# Remove or set false in systemd drop-in or environment
export HERMES_SERVICE_RESTART_CANARY_V2_ENABLED=false
export HERMES_SERVICE_RESTART_CANARY_V2_MODE=off
```

## Canary Fixture Lifecycle

`CANARY_SERVICE_LIFECYCLE=KEEP_RUNNING_AS_HARMLESS_TEST_FIXTURE`

Do not stop or remove the service during baseline consolidation. Cleanup is a
separate service mutation and requires separate operator approval.

## Hard Fail Conditions

The sprint FAILS if any of the following occur:
- Wrong service restarted
- Restart count >1 successful
- Restart adapter calls > allowed
- Unregistered service mutated
- Gateway mutated
- Public stop/start succeeds
- Kill/signal executed
- SYSTEM_CONTROL enabled
- Generic SERVICE_CONTROL enabled
- Reload authority silently grants restart
- Identity mismatch accepted
- Old process survives but success declared
- NOT_QUIESCENT accepted
- Orphan accepted
- Wrong executable/user/cgroup/port accepted
- Bad pre-health restart executed
- Approval bypass
- Budget/breaker bypass
- Duplicate restart executed
- UNKNOWN_OUTCOME retried
- Restart used as rollback retry
- Post-health failure committed
- DB corrupted
- Secret leak
- NEW_REGRESSION > 0
- Kill-switch fails
