# Hermes 2.0 — Sprint 1.3.15 — Multi-Service Coordination Recovery

> **Durable-evidence-driven recovery. No blind replay, no auto-retry.**
> Module: `agent/multi_service_coordination/recovery.py` + `_durable.py`.

## Principle

Recovery never reads in-memory status strings as authority. It classifies
from **durable journal evidence** (the append-only event journal) and, where
present, from durable child outcomes. `UNKNOWN` evidence → manual review.

## Global recovery states

| State | When |
|---|---|
| `SAFE_TO_ABORT` | claimed but no durable progress beyond preparation |
| `SAFE_TO_CONTINUE_VERIFY` | claim + simulation started, verify not terminated |
| `COMPENSATION_REQUIRED` | durable partial-failure / compensation marker present |
| `MANUAL_REVIEW_REQUIRED` | ambiguous / foreign holder / unknown evidence |
| `TERMINAL` | durable `GLOBAL_SIMULATED_COMMIT` / `GLOBAL_FAILED` / compensation failure |
| `UNKNOWN` | no durable evidence, or a child outcome is `UNKNOWN` → manual review |

## Crash matrix (each checkpoint is fail-closed)

| Crash point | Durable evidence left | Disposition |
|---|---|---|
| after global claim | `GLOBAL_CLAIMED` | `SAFE_TO_ABORT` |
| after lock A / lock B / all locks | `LOCK_ACQUIRED` | `SAFE_TO_ABORT` |
| after prepare A / B | `CHILD_PREPARED` | `SAFE_TO_ABORT` |
| after barrier | `BARRIER_READY` | `SAFE_TO_ABORT` |
| after simulated execution A | `SIMULATION_STARTED` + `CHILD_SIMULATED` | `SAFE_TO_CONTINUE_VERIFY` |
| before verify | `CHILD_SIMULATED` | `SAFE_TO_CONTINUE_VERIFY` |
| during compensation classification | `CHILD_FAILED` / `COMPENSATION_REQUIRED` | `COMPENSATION_REQUIRED` |
| before simulated commit | `VERIFY_COMPLETED` (no commit) | never `TERMINAL` |

A crash never produces a decision that implies blind replay. An ambiguous
(claimed + simulated) journal asks for verification, never auto-replays.

## Compensation model

`CompensationPlan` is built deterministically in **reverse topological order**
(dependents compensated before their dependencies), not a reversed input list.
Each `CompensationStep` declares its action, preconditions, ordering, evidence
and an `unsupported` flag. If any REQUIRED child lacks rollback/compensation
proof, the parent is `COMPENSATION_REQUIRED` — a partial failure is never
reported as partial success.

## Exactly-once idempotency

Semantic key = baseline + service set + operation set + config fingerprints +
registry digest + graph digest (time-invariant). A duplicate global intent
returns the prior simulated result with **zero** new approvals, budgets,
simulations or adapter calls. A durable terminal record is replayed regardless
of owner (the semantic intent is already decided).

## Store atomicity

All durable state transitions go through `JsonTransaction`
(temp + fsync + rename + fsync parent). Critical transitions are atomic; a
partial JSON write can never leave a truncated record. The coordination store
is Hermes-owned and isolated — it is **not** `state.db`.