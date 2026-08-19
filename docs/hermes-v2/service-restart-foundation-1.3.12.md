# Service Restart Foundation — Sprint 1.3.12

A shadow/fake-only foundation that *models* controlled restart semantics for
Hermes auxiliary services. It proves and rehearses the full RESTART lifecycle
(PID transition → quiescence → start → verify → stabilization) WITHOUT ever
executing a production restart.

**PRODUCTION RESTART EXECUTION = 0 in 1.3.12.**

## Authority model

RESTART is a SEPARATE authority contract from RELOAD. Nothing in the reload
policy grants restart, and nothing in this foundation derives a restart right
from reload rights. There is no code of the form
`if reload_allowed: restart_allowed = True`.

| Control | Value |
|---|---|
| SYSTEM_CONTROL | OFF |
| generic SERVICE_CONTROL | DENIED |
| RESTART / STOP / START / KILL / SIGNAL | DENIED |
| Restart execution (production) | 0 |
| Kill-switch | ON |

## Architecture

```
ServiceFoundation
  → LimitedServiceReloadPolicy
  → RestartFoundation          (new)
      → RestartEligibility
      → RestartPlan
      → PIDTransitionModel
      → QuiescenceCheck
      → StartupContract
      → HealthContract
      → Rollback/RecoveryPlan
      → SHADOW / FAKE ONLY
```

Execution guard: `RestartPlan.execute()` → `SERVICE_RESTART_DISABLED`.

## Key principle

**RESTART ELIGIBLE != RESTART AUTHORIZED.** Even a service that evaluates to
`ELIGIBLE_FOR_FUTURE_RESTART_CANARY` cannot be restarted — the execution guard
always blocks in 1.3.12 with `adapter_calls == 0`.

## Files

```bash
agent/service_restart_foundation/
  __init__.py  flags.py  models.py  registry.py  exceptions.py
  eligibility.py  pid_transition.py  quiescence.py  orphans.py  ports.py
  stop_contract.py  start_contract.py  identity_after_start.py
  dependencies.py  blast_radius.py  risk.py  plan.py  guard.py  gateway.py
  unknown_outcome.py  recovery.py  rollback.py  approval.py  budget.py
  circuit_breaker.py  shadow.py  chaos.py  events.py  telemetry.py  cli.py
```

Fraud-guard: no production restart/stop/start adapter exists in this module.

## Next

1.3.12.1 — restart foundation baseline consolidation, then 1.3.13 — single
auxiliary service restart canary. Neither is started automatically.