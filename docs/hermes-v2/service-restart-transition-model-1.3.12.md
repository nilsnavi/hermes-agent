# Service Restart Transition Model — Sprint 1.3.12

Pure model of the controlled restart lifecycle, exercised in shadow / fake
runtime / deterministic chaos and read-only production observation only.

## Lifecycle being modelled

```
RUNNING → STOPPING → STOPPED → STARTING → RUNNING → VERIFY → STABILIZATION → COMMIT
```

## PID transition

Restart success **requires `new_pid != old_pid`** unless a service contract
proves otherwise. PID reuse is detected through **PID + process-start
identity**, never PID alone:

- same PID + same start identity → old PID survives → FAIL
- same PID + different start identity → PID reuse detected → FAIL
- new start identity empty → FAIL
- executable / user / cgroup mismatch → FAIL

## Stop contract

Expected unit transition `active/running → deactivating → inactive/dead`.
`evaluate_stop` is pure analysis; it never issues a real stop (fake runtime
only).

## Quiescence gate

Between stop and start a `QuiescenceGate` checks: old MainPID gone, old
process-start identity gone, no children, no orphan workers, expected ports
released, no stale pidfile, unit reached expected stopped state. Result is
`QUIESCENT | NOT_QUIESCENT | UNKNOWN`. Only `QUIESCENT` allows a future start.

## Orphan detection (P0)

Any orphan — parent dies + child survives, old cgroup member survives, forked
worker detached, stale pidfile, wrong socket owner — is `RESTART_UNSAFE` and
denies future autonomous restart.

## Port transition

Before: listener owned by old service identity. Stop: listener disappears.
After start: listener owned by the new verified PID/service identity. Wrong PID
owns a port → FAIL. Unexpected public listener → risk up / DENY.

## Start contract / post-start identity

The new process must match expected executable, user, cgroup and unit, and carry
a new process-start identity. Executable change after restart →
`IDENTITY_CHANGED_AFTER_RESTART` → FAIL.

## Dependency quiescence & blast radius

Restart safety is never judged by the service alone. Critical/active dependents,
shared resources, bound units (Requires/Wants/BindsTo/PartOf) are checked. Any
cascade risk escalates blast radius to `MULTI_SERVICE`. In 1.3.12 future
autonomous restart requires blast radius ≤ `SERVICE`.

## Risk monotonicity

Restart baseline risk **must not be lower than reload risk**. A profile cannot
be used to lower restart risk. Reload baseline = `MEDIUM_MUTATION`; restart
baseline = `HIGH`.

## Verification

Covered by `tests/service_restart_foundation/` (PID transition, quiescence,
orphans, ports, stop/start contracts, post-start identity, dependency/blast,
risk, plan + revalidation, unknown outcome, recovery, rollback, execution guard,
gateway deny, shadow, chaos).