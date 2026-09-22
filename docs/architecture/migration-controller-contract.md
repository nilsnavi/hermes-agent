# Migration controller contract

## Purpose and boundary
Control-plane-only immutable contract. It never routes traffic, invokes providers/tools/delivery, mutates sessions, writes production DB, sleeps, or loads secrets.

## Baseline and runtime observations
Inspected `docs/architecture/runtime-migration-controller.md`, `docs/architecture/migration-readiness-gate.md`, `docs/architecture/adapter-boundary-design.md`, `docs/architecture/session-persistence-projection.md`, `hermes_core/domain/`, `hermes_core/application/`, `hermes_core/ports/`, `gateway/run.py`, `gateway/session.py`, `hermes_state.py`. Production ownership remains current runtime (VERIFIED); live migration wiring and legal production graph are UNVERIFIED.

## Phases and ownership
Phases are OFF, SHADOW, CANARY, DRAINING, CUTOVER, ROLLBACK. Authoritative owner remains CURRENT; candidate is represented separately. Shadow/canary never transfer ownership.

## State, fencing and scope
State carries phase, owners, generation, kill switch, drain state and bounded profile/session scope. Requests carry expected generation; successful changes increment once; stale requests return CONFLICT. Empty scope fails closed.

## Transition graph
OFF→SHADOW→CANARY→DRAINING→CUTOVER; rollback is explicit from CANARY/DRAINING/CUTOVER and returns to OFF. Arbitrary jumps are rejected.

## Kill switch and drain
Generation-fenced kill switch blocks forward migration. DRAIN_REQUESTED is distinct from DRAINED; cutover requires DRAINED.

## Rollback/failover
Rollback is state authorization only and never executes external reversal. Failover is represented by `MigrationController.failover()` but is fail-closed: runtime semantics are UNVERIFIED and the operation returns `FAILOVER_NOT_ALLOWED/failover_unverified` without mutation.

## Audit and persistence
AuditEvent is immutable and contains transition/generation/status/owner evidence without secrets. Future persistence must use B1/B2-compatible CAS; no DB adapter is implemented.

## Adapter responsibilities and gaps
Adapters eventually own durable state, runtime drain observation, ownership execution and audit persistence. B6 is PARTIALLY_ADDRESSED; production migration is NO-GO.
