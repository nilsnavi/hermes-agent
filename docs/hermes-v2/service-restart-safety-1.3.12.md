# Service Restart Safety — Sprint 1.3.12

## Hard fails that would sink the sprint

- production restart/stop/start/process-signal > 0
- gateway mutation > 0
- SYSTEM_CONTROL enabled, generic SERVICE_CONTROL enabled
- reload authority accidentally expanded into restart
- execute(plan) succeeds
- identity mismatch / orphan / NOT_QUIESCENT accepted
- old PID survives and is treated as success
- port conflict / wrong executable / wrong user / stale graph accepted
- blast radius > SERVICE accepted
- UNKNOWN_OUTCOME auto-retried
- restart used as rollback retry
- risk decreases
- secret leak / DB corruption
- NEW_REGRESSION > 0

## Safety invariants (all hold at the end of 1.3.12)

- restart execution = 0
- stop execution = 0
- start execution = 0
- kill/signal execution = 0
- new production reload = 0
- gateway restart = 0
- SYSTEM_CONTROL = OFF
- generic SERVICE_CONTROL = DENIED
- reload kill-switch = ON

## Flags (Sprint 1.3.12)

```
HERMES_SERVICE_RESTART_FOUNDATION_V2_ENABLED=false
HERMES_SERVICE_RESTART_FOUNDATION_V2_MODE=off
```

Modes: off | shadow | inspect. NOT canary/execute/enforce. Unknown mode → off.

## Gateways & systemctl

The restart foundation accepts no raw command, no shell string, no arbitrary
unit. Forbidden surface: `systemctl restart|stop|start`, `service ...`,
`kill`, `pkill`, `signal`. There is no production runner and no
production restart adapter.

## Documented principle

**RESTART ELIGIBLE != RESTART AUTHORIZED.**

## Artifacts

- `agent/service_restart_foundation/` — shadow/fake modules + P0 guard + CLI
- `tests/service_restart_foundation/` — targeted tests (RED→GREEN)
- `docs/hermes-v2/service-restart-*-1.3.12.md` — this series