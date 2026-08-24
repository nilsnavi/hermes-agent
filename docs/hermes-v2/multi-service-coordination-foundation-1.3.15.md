# Hermes 2.0 — Sprint 1.3.15 — Bounded Multi-Service Coordination Foundation

> Status: **SHADOW / REHEARSAL ONLY — NO LIVE EXECUTION** · Date: 2026-08-24
> Baseline: `f9982e629823404421a760057f1d8ce9dfab1a67` (1.3.14.1, tag `hermes-v2-limited-restart-policy-1.3.14`)
> Module: `agent/multi_service_coordination/` · Tests: `tests/multi_service_coordination/`

## Objective

Prove the correctness of a coordinating change-across-services layer **before**
any live multi-service mutation authority exists. Sprint 1.3.15 adds **zero**
production mutation authority: no real execution, no stop/start, no signal, no
gateway mutation, no registry expansion.

## Architecture

The coordinator is **not** a new system-control layer. It sits on top of the
existing safety stack and only aggregates their decisions:

```
CapabilityPolicyEngine -> VerifiedToolExecutor -> SystemBoundaryLayer
  -> TransactionalChangePipeline -> LimitedProductionMutationPolicy
  -> ServiceFoundation -> LimitedServiceReloadPolicy -> RestartFoundation
  -> LimitedRestartPolicy -> MultiServiceCoordinator
```

The coordinator **cannot**:
* resolve a new operation,
* raise authority,
* add a service to any registry,
* bypass any per-service policy / approval / lock / budget / breaker /
  health / rollback / idempotency gate,
* turn a child DENY into an ALLOW,
* perform any real child execution (`execution_guard` always returns
  `MULTI_SERVICE_EXECUTION_DISABLED`, adapter calls == 0).

## Components

| File | Purpose |
|------|---------|
| `models.py` | Immutable `MultiServiceChangePlan`, `ServiceSubPlan`, `GlobalTransaction`, `ServiceTransaction`, `PrepareBarrier`, `PreparedServiceToken`, `CompensationPlan`, `MultiServiceExecutionPermit`, strict state machine |
| `transaction.py` | `MultiServiceCoordinator` — sole authority orchestrator driving the global state machine |
| `graph.py` | Bounded dependency graph, canonical topological order, cycle detection, desired-order validation |
| `lock_order.py` | **Canonical deterministic lock order** (P0 deadlock prevention) |
| `eligibility.py` | All-or-nothing eligibility aggregation (child DENY → parent DENY) |
| `planner.py` | Immutable plan construction + validation (registry, blast, risk, order) |
| `prepare.py` / `barrier.py` | Per-service prepare gates + `PrepareBarrier` |
| `idempotency.py` | Global semantic-key exactly-once coordination |
| `approval.py` / `budget.py` | Global approval binding + coordination budget (production usage stays 0) |
| `compensation.py` / `recovery.py` | Reverse-topological compensation + evidence-driven recovery classifier |
| `execution_guard.py` | **P0 guard — always `MULTI_SERVICE_EXECUTION_DISABLED`** |
| `_durable.py` / `events.py` | Isolated durable store + append-only event journal |
| `telemetry.py` | Counters (`real_adapter_calls` read-only, always 0) |
| `evaluation.py` | Shadow study (500) + rehearsal (500) harness |
| `cli.py` | Read-only inspection + `shadow-evaluate` (no execute) |

## Global state machine

```
CREATED -> PLANNED -> ELIGIBILITY_CHECKED -> LOCKS_ACQUIRED -> PREPARED
  -> BARRIER_READY -> EXECUTION_READY -> SIMULATED_EXECUTING -> VERIFYING
  -> COMMIT_READY -> COMMITTED_SIMULATED

Failure corridor (from any non-terminal): DENIED / LOCK_FAILED /
PREPARE_FAILED / BARRIER_FAILED / CHILD_FAILED / VERIFY_FAILED /
COMPENSATION_REQUIRED / COMPENSATION_FAILED / UNKNOWN_OUTCOME /
MANUAL_REVIEW_REQUIRED
```

There is **no** real `EXECUTING` state and **no** real adapter call.

## Guarantees proven

* All-or-nothing eligibility (a single child DENY denies the parent).
* Canonical lock ordering → distributed deadlock structurally impossible;
  at most one active writer per service.
* No execution before all children prepared (barrier).
* No silent partial success (failure → COMPENSATION_REQUIRED, never SUCCESS).
* Child UNKNOWN outcome → UNKNOWN_OUTCOME, `AUTO_RETRY=false`.
* Global exactly-once idempotency (duplicate intent replays prior result with
  no second approval/budget/simulation).
* Risk monotone non-decreasing; blast parent = max + coupling amplification.
* Immutable plans; denied targets (gateway/scheduler/provider/db/network/
  auth/security/docker/ssh/unknown/unregistered) always resolve to DENY.

## Scope limits (Sprint 1.3.15)

* Services: existing `hermes-aux-canary` + fake `fake-aux-a` / `fake-aux-b`
  (sandbox-only, non-systemd, no host side effect).
* Bounds: max 3 services, max depth 4, max edges 16; over-limit → DENY.
* Flags: `HERMES_MULTI_SERVICE_COORD_V2_ENABLED` / `..._MODE`
  (`off | shadow | rehearsal`). Unknown mode → `off`. No live/canary mode.

## Verification

* Scoped canonical: `scripts/run_tests.sh tests/multi_service_coordination`
  → **154 passed / 0 failed**.
* Shadow study: 500 evaluations, **correctness 100%, mutations 0, adapter 0**.
* Rehearsal: 500 scenarios, **violations 0, real mutations 0, adapter 0**.
* Concurrency: 20 concurrent global transactions — deadlock 0, double-writer 0,
  adapter 0, duplicate claim correct.
* Negative matrix: **55+ explicit DENY cases**.
* Full canonical regression and nodeid delta: see the Sprint 1.3.15 final report.

Safety companions:
`multi-service-coordination-safety-1.3.15.md`,
`multi-service-coordination-recovery-1.3.15.md`,
`multi-service-coordination-runbook-1.3.15.md`.