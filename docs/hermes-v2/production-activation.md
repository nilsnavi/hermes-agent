# Production Activation — Hermes V2

Updated: Sprint 1.1.1

## Current activation status (Stage 6 / operations)

| Component | Status |
|---|---|
| Read-Only Canary | **ACTIVE** |
| Shadow | **ACTIVE** (explicit only, zero tool calls) |
| Global V2 routing | **OFF** — ordinary traffic 100% LEGACY |
| Persistence | **ACTIVE** |
| Intent Router | **ACTIVE — OBSERVE ONLY** (Sprint 1.1.1; zero routing authority) |
| Approval Foundation | **ACTIVE** (operational layer) |
| Operations Observability | **ACTIVE** |

## Feature flags (live)

```
HERMES_RUNTIME_V2_ENABLED=true
HERMES_RUNTIME_V2_ORCHESTRATOR=true
HERMES_RUNTIME_V2_SHADOW=true
HERMES_RUNTIME_V2_CANARY=true
HERMES_RUNTIME_V2_PERSISTENCE=true
HERMES_INTENT_ROUTER_ENABLED=true
HERMES_INTENT_ROUTER_MODE=observe
```

Mode guard: only OFF / OBSERVE are allowed in production; ENFORCE and
SHADOW_DECISION fail closed to OFF in code (§6). Router is observer-only:
actual route never depends on its decision. See
`docs/hermes-v2/intent-router-observe.md` for flags, telemetry schema,
metrics, rollback and incident procedure.

## Safety invariants (must hold)

- Write/unknown tools in canary: **0 executions**
- Duplicate responses: **0**
- Ordinary traffic routed to V2: **0** (explicit internal allowlist only)
- Secret findings in V2 data: **0**
- DB locks / orphan rows: **0**
- Read-only canary success rate: **≥ 95%** excluding deliberate failure tests
  (deliberate tests are counted honestly, never masked)

## Canary allowlist

Explicit internal allowlist only. The allowlist is never broadened without a
dedicated sprint.

## Kill switch

- `kill_switch_available: true` — flag control, runbook and gateway control
  all present.
- Kill switch never fires automatically; disabling V2 is an operator action.

## Change freeze

Provider/model routing, scheduler routing, Telegram transport and the legacy
runtime are unchanged in this sprint.

## Roadmap

- **Sprint 1.1.1** — Intent Router PRODUCTION OBSERVE (calibration) — done.
- **Sprint 1.2.0** — Controlled Intent Routing Enforcement (if safety green
  + sufficient sample) or **Sprint 1.1.2** — Calibration Hardening.

## Intent Router prerequisites (design only)

1. Observable runs (this sprint).
2. Stable success/error metrics (this sprint).
3. Risk policy — read vs write classification per tool.
4. Eligibility policy — which task types may route to V2.
5. Kill switch — operator-controlled disable.
6. Approval foundation — human gate for staged requests.
7. Canary history — sustained success over time window.
