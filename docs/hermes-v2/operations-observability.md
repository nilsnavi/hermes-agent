# Operations Observability — Hermes V2

Sprint 1.0.6.3 · Status: **ACTIVE** · Layer: `agent/operations_v2/`

## Overview

The operations layer gives the operator read-only visibility into the
Read-Only Canary runtime without expanding the execution surface. It is a
**separate layer above the execution engine** — it never calls tools, never
writes to the legacy runtime, and never routes traffic.

```
         Gateway V2
             |
      RuntimeOrchestrator
             |
          Store
             |
    +--------+---------+
    |                  |
Observability        Approval Service
|                  |
Run Inspector        Approval Controller
Event Summary        Operator Decisions
Health Metrics       Audit Trail
Manual Review        Recovery Resume
```

## Components

| Module | Responsibility |
|---|---|
| `models.py` | Safe DTOs (never raw payloads), enums, health model |
| `run_inspector.py` | Read-only run/step/event inspection |
| `metrics.py` | Aggregates from `agent_v2_runs/steps/approvals/events` |
| `health.py` | HEALTHY / DEGRADED / UNHEALTHY model + structured findings |
| `approval_service.py` | Durable approve / reject / expire with version guards |
| `manual_review.py` | Reconstructs manual-review queue from durable events |
| `service.py` | Facade binding inspector + metrics + health + approvals |
| `serializers.py` | Stable JSON serialization (no secret fields) |
| `exceptions.py` | Operations error taxonomy |
| `cli.py` | Operator CLI (read-only by default) |

## Data sources

All metrics are computed from existing V2 tables — no telemetry DB:

- `agent_v2_runs` — run lifecycle
- `agent_v2_plans` — plan lifecycle
- `agent_v2_steps` — step lifecycle + tool names
- `agent_v2_approvals` — durable approval decisions
- `agent_v2_events` — append-only event stream (hashed payloads only)

## Key guarantees

- **No raw payloads**: summaries and timelines expose scalar/enum fields only.
  Inputs/outputs are referenced by `input_hash` / `output_hash`.
- **Read-only**: inspection queries run with `mode=ro` connections.
- **Bounded pagination**: list default 50, max 500; timeline cursor-based.
- **No N+1**: aggregation uses SQL, not per-row queries.

## Metric windows

`last 1h` · `last 24h` (default) · `all`

## Success rate

```
canary_success_rate = completed canary runs / terminal canary runs
```

Excludes legacy/shadow traffic and intentionally staged approval-waiting
runs. Deliberate failure tests are counted honestly (never masked) — the
denominator is always reported alongside the rate.

## Health model

| Status | Condition |
|---|---|
| HEALTHY | gateway active, DB healthy, no unexpected reviews, read-only guard active |
| DEGRADED | stale approval, single timeout, pending manual review, high failure rate |
| UNHEALTHY | DB integrity failure, write tool detected, duplicate response, ordinary traffic routed V2 |

## Alert codes

`SAFETY_WRITE_EXECUTED`, `DUPLICATE_RESPONSE`, `SECRET_LEAK`,
`ORDINARY_TRAFFIC_V2`, `DB_INTEGRITY_ERROR`, `DB_LOCK_LOOP`,
`GATEWAY_RESTART_LOOP`, `CANARY_FAILURE_RATE_HIGH`, `STALE_APPROVAL`,
`MANUAL_REVIEW_PENDING` — structured findings only; no external alert
integration yet.
