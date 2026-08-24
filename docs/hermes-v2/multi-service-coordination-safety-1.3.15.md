# Hermes 2.0 — Sprint 1.3.15 — Multi-Service Coordination Safety

> **SHADOW / REHEARSAL ONLY. NO LIVE EXECUTION. NO AUTHORITY EXPANSION.**
> Baseline: `f9982e629823404421a760057f1d8ce9dfab1a67`
> Coordinator: `agent/multi_service_coordination/`

## Production authority (unchanged, verified read-only)

| Authority | State |
|---|---|
| `SYSTEM_CONTROL` | **OFF / DENIED** |
| Generic `SERVICE_CONTROL` | **DENIED** |
| Public stop/start | **DENIED** |
| Signal API | **DENIED** |
| Gateway self-control | **FORBIDDEN** |
| Restart registry size | **1** (`hermes-aux-canary.service`) |
| Kill-switch | **ON** |
| Live multi-service authority | **NONE** (this sprint grants none) |

## No second policy engine

The brief forbids a parallel `MultiServicePolicyEngine`. The coordinator
`eligibility.py` only **aggregates** the verdicts it is given from each child's
own policy layer. Rules:

```
child DENY    -> parent DENY
child UNKNOWN -> parent DENY / REVALIDATE_REQUIRED
child ALLOW   -> parent ALLOW only if ALL children ALLOW
```

The coordinator never converts a DENY into an ALLOW.

## P0 execution guard

Even when every plan, approval, lock, budget and health gate is green, the
execution guard hard-returns `MULTI_SERVICE_EXECUTION_DISABLED` and
`real_adapter_calls == 0`. There is no code path that can call a real child
adapter.

## No authority leak

The coordinator does **not** export raw child executors, raw execution grants,
commit authority, a service-control handle, or a systemctl wrapper. No
`subprocess`, no `os.system`, no `shell=True`, no dynamic import authority,
no `eval`/`exec`, no caller-provided executable authority.

## All-or-nothing eligibility

Before prepare, **all** child services must be eligible. If

```
A ALLOW, B ALLOW, C DENY  ->  parent DENY
```

Partial execution is never attempted.

## Canonical lock order (P0 — deadlock prevention)

All service locks are acquired in one canonical deterministic order derived
from a stable sorted service-identity digest — **never** the caller's request
order. Two transactions requesting the same service set always take locks in
the same global order, so distributed deadlock is structurally impossible.
Invariant: at most one active writer per service.

## Scope limits

* Services: `hermes-aux-canary` (existing), `fake-aux-a`, `fake-aux-b`
  (sandbox-only fake, not a systemd target, no host side effect).
* Graph bounds: max 3 services / depth 4 / edges 16. Over-limit → DENY.
* Cycle, UNKNOWN dependency, STALE graph, CORRUPT graph → DENY / revalidate.
* Parent blast accepted only within `RESOURCE / SERVICE / MULTI_SERVICE`;
  `HOST / NETWORK / UNKNOWN` → DENY.

## Flags

| Variable | Allowed | Meaning |
|---|---|---|
| `HERMES_MULTI_SERVICE_COORD_V2_ENABLED` | `true/false/1/0/yes/no` | master gate |
| `HERMES_MULTI_SERVICE_COORD_V2_MODE` | `off/shadow/rehearsal` | mode |

Unknown or absent mode → `off`. **No live/canary mode exists in 1.3.15.**

## Negative matrix (always DENY)

`gateway`, `scheduler`, `provider`, `database`, `network`, `auth`, `security`,
`docker`/`container`, `ssh`, any unknown/unregistered service → DENY. The
negative matrix ships **55+ explicit negative cases** covering every listed
target.

## Telemetry invariants

* `plans_total`, `plans_denied`, `prepare_failures`, `lock_failures`,
  `deadlock_avoided`, `duplicate_global_intents`, `unknown_outcomes`,
  `compensation_required`, `simulated_commits`.
* `real_adapter_calls` is read-only and must remain **0** at all times.