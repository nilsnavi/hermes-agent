# Hermes 2.0 — Sprint 1.3.15 — Multi-Service Coordination Operator Runbook

> **Operator document.** Everything here is **read-only observation** or
> shadow/rehearsal evaluation. There is **no execute command** to run.

## 1. Feature flags

```bash
# mode: off | shadow | rehearsal  (unknown -> off)
HERMES_MULTI_SERVICE_COORD_V2_ENABLED=true
HERMES_MULTI_SERVICE_COORD_V2_MODE=shadow
```

There is **no live/canary mode** in Sprint 1.3.15. `live_execution_permitted()`
is hard-wired `False`.

## 2. Read-only inspection

```bash
python -m agent.multi_service_coordination.cli inspect-graph
python -m agent.multi_service_coordination.cli inspect-plan <transaction_id>
python -m agent.multi_service_coordination.cli inspect-transaction <transaction_id>
python -m agent.multi_service_coordination.cli shadow-evaluate --n 500
```

The CLI has intentionally **no** `execute` subcommand.

## 3. Shadow study

```bash
python -m agent.multi_service_coordination.cli shadow-evaluate --n 500
```

Expect: `correctness == 100`, `real_multi_service_adapter_calls == 0`,
`mutations == 0`.

## 4. Production read-only observation (before/after)

```bash
for u in hermes-gateway.service hermes-aux-canary.service; do
  systemctl --user show "$u" -p MainPID -p NRestarts -p ActiveState -p SubState -p ExecMainStatus
done
```

Sprint 1.3.15 must leave these **unchanged** (no restart, no reload, no
stop/start, no signal). Expected: `NRestarts=0`, `ActiveState=active`,
`SubState=running`, `ExecMainStatus=0`.

## 5. Hard constraints (HARD FAIL if violated)

* multi-service adapter call > 0
* restart registry size > 1
* production mutation > 0
* `SYSTEM_CONTROL` enabled / generic `SERVICE_CONTROL` enabled
* gateway authority added / public stop-start enabled / signal API enabled
* child DENY overridden / UNKNOWN treated as ALLOW
* partial success returned as SUCCESS / deadlock possible
* two writers same service / lock order caller-controlled / cycle executes
* duplicate consumes a second approval or budget / duplicate simulated twice
* live-owner lock stolen / risk decreased / blast incorrectly reduced
* rollback unsupported accepted as safe / NEW_REGRESSION>0 / secret leak / stale codemap

## 6. Scope

Sprint 1.3.15 coordinates only `hermes-aux-canary` (existing, read-only
authority) plus the sandbox-only fakes `fake-aux-a` and `fake-aux-b` (not
systemd targets, no host side effect). The production restart registry stays at
size 1. No live multi-service change is performed.