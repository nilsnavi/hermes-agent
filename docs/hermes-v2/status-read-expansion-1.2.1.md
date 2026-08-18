# Sprint 1.2.1 — STATUS_READ Expansion + SEARCH_READ Shadow Study

> Date: 2026-08-13 · Hermes Agent 2.0 · Intent Router enforcement series
> Baseline: Sprint 1.2.0 PASS (STATUS_READ enforcement stable, 60m window green).

## 1. What changed

The enforcement allowlist and tool surface grew from the 1.2.0 baseline
(5 phrases, 2 tools) to the full STATUS_READ family (§2/§4/§6):

| Area | 1.2.0 | 1.2.1 |
|---|---|---|
| Allowed intent | STATUS_READ | STATUS_READ (unchanged) |
| Sub-intents | — (single) | 7 deterministic subtypes (§2) |
| Allowlist phrases | 5 | 19 (8 RU + 7 EN + 5 baseline, dedup) |
| Verified tools | runtime_status, canary_ping | + gateway_status, provider_status, scheduler_status, integration_status, health_status |
| SEARCH_READ | LEGACY (INTENT_NOT_ALLOWED) | **Shadow study** (§9-12): classified, candidate built, actual route ALWAYS LEGACY |

## 2. STATUS_READ sub-intents (§2)

Deterministic `StatusSubtype` enum + first-match marker detection
(`enforcement.detect_status_subtype`, most specific first):

| Subtype | Markers | Primary tool |
|---|---|---|
| service_status | hermes, сервис, служб | runtime_status |
| gateway_status | gateway | gateway_status |
| runtime_status | runtime, рантайм | runtime_status |
| health_status | health, здоровь | health_status |
| integration_status | telegram, mcp, интеграц | integration_status |
| scheduler_status | scheduler, cron, крона | scheduler_status |
| provider_status | provider, провайдер | provider_status |
| generic (fallback) | — | runtime_status |

Every subtype maps to a REAL registered tool in the canary registry
(§4 — no invented APIs); `canary_ping` remains the shared fallback.
The gateway executes at most ONE tool per enforced run
(`eligible_tools[0]`).

## 3. Allowlist expansion (§6)

19 explicit phrases, word-boundary matched on normalized text:

- RU: `статус hermes`, `состояние gateway`, `покажи health`,
  `работает ли telegram`, `статус scheduler`, `какой сейчас provider`,
  `состояние mcp`, `покажи состояние runtime` + 3 baseline RU
- EN: `hermes status`, `runtime health`, `telegram status`,
  `scheduler status`, `provider status`, `mcp status` + baseline
  `gateway status`, `health hermes`

Classifier vocabulary: ONLY precise provider-status phrases were added
(`какой сейчас provider`, `какой провайдер`, `какой provider`,
`which provider`, …). A bare `provider`/`mcp`/`telegram` word was
deliberately NOT added to `_STATUS_READ` — it would have flipped
mutating requests (`подключи mcp`, `посмотри provider и переключи
модель`) into STATUS_READ. Verified empirically before committing.

## 4. READ-ONLY contract (§5)

`STATUS_TOOL_METADATA` mirrors the real registry: every enforced tool
must carry `side_effect=READ_ONLY` + `idempotent=true`. The policy's
new TOOL_METADATA gate (8th in the ladder) blocks enforcement for a
tool whose metadata is missing/not READ_ONLY/not idempotent →
LEGACY. Registry↔table coherence is tested
(`test_canary_registry_matches_metadata_contract`).

New tools are local-only file reads:

- `gateway_status` — `gateway_state.json` scalars (never argv/env/paths)
- `provider_status` — provider_models_cache.json ids/counts (§16: no
  model switch, no probe with side effect, no credential refresh)
- `scheduler_status` — `cron.jobs.load_jobs()` count/ids (§17:
  list/count/status only — no create/update/delete/pause/resume)
- `integration_status` — platforms section of gateway_state.json
  (Telegram/MCP/API/HA states; no reconnect/start/restart, §18)
- `health_status` — local synthesis (gateway_state + platforms
  needs_attention; NO OperationsService probe, no network)

## 5. SEARCH_READ shadow study (§9-12)

`router._search_shadow_eval` — SEARCH_READ requests are classified and
a candidate V2 decision is BUILT (capability analysis: SEARCH ∉
verified V2 surface → missing capability; policy: SEARCH_READ ∉
enforced intents → policy blocked), but:

- actual route is ALWAYS `LEGACY` (§10 invariant — actual V2 runs = 0)
- no V2 tool execution, no user-visible V2 response
- aggregates ONLY (`search_shadow_*` counters in RouterStats; no raw
  prompts persisted, §12)

Metrics (§9): `search_shadow_total`, `search_shadow_candidate_v2`,
`search_shadow_missing_capability`, `search_shadow_policy_blocked`,
`search_shadow_confidence_sum`, `search_shadow_latency_sum_ms`.
Block reason `SEARCH_SHADOW_ONLY` marks the outcome; `search_shadow`
flags in EnforcementOutcome.to_dict().

## 6. Safety (§14)

Must stay zero — all verified zero in offline eval and suite:

- WRITE/DELETE/SYSTEM/SCHEDULE/APPROVAL/UNKNOWN routed V2 = 0
- SEARCH_READ actual V2 = 0
- unsafe_as_read_only = 0, unsafe_as_canary = 0

Mixed intent (§8): unsafe always wins (proven classifier precedence,
"покажи статус и перезапусти gateway" → SYSTEM → LEGACY).

## 7. Metrics (§13/§19)

Per-subtype counters (`enforcement_by_subtype`): attempts/allowed/
blocked/success/failure/fallback per status subtype. Performance:
router decision p50/p95 from the in-memory ring (<5 ms target);
new tools bounded at 2.0 s timeout.

## 8. Activation & rollback

Same drop-in as 1.2.0 (`sprint112-enforce.conf`,
`HERMES_INTENT_ROUTER_MODE=enforce_status_read`) — the mode string is
unchanged; the code expansion is additive. Rollback: set MODE=observe
or ENABLED=false + external gateway restart (§28).

## 9. Tests (§24)

`tests/intent_router/test_status_expansion.py` — 44 tests:
7 subtype-enforced parametrized, allowlist 19 phrases, SEARCH_READ
shadow-only (5 phrases), never-actual-V2 invariant, shadow aggregates
no raw prompts, 9 negative/mixed LEGACY cases, metadata contract
(required/read_only/idempotent/unknown/failed-closed drift), registry
coherence, unhealthy/degraded/unknown fallback, subtype detection
units, subtype-tools-are-real. 1.2.0 tests updated for the new
contract (allowlist 5→19, SEARCH_READ shadow reason).

## 10. Offline evaluation (§25)

Dataset extended 382 → **416** (34 new STATUS_READ expansion cases:
15 §6 phrases, 10 negatives, 5 mixed, 5 shadow). Result: 416/416,
accuracy 1.0, unsafe_as_read_only 0, unsafe_as_canary 0.

## 11. Results

- Canonical scope: 81 files / **755 passed / 0 failed** (was 78/710 at
  1.2.0). Fresh scoped re-verification (tests/intent_router +
  test_canary_activation): 247/247.
- enforce-suite: **28/28** (E1-E10 + S1-S7 + N1-N8 + SH1-SH3), search
  actual V2 = 0, search_shadow total=4 / candidate_v2=0 / actual=0.
- Offline eval: **416/416** (382 baseline + 34 new), accuracy 1.0,
  unsafe_as_read_only 0, unsafe_as_canary 0.
- Live (2026-08-13, gateway PID 154814): S1-S7 → V2_CANARY one tool
  each (runtime_status/gateway_status/integration_status/
  scheduler_status/provider_status in `agent_v2_steps`, 8×V2_OK in
  journald), N1-N8 → LEGACY, SEARCH_READ shadow → LEGACY
  (SEARCH_SHADOW_ONLY, live observation 17:40:09).
- Stability: 60m window PASS — MainPID=154814 constant, NRestarts=0,
  RSS/threads/FDs normal, SQLite locks 0, Telegram healthy, scheduler
  & provider unchanged. Gateway still live 5h+ after activation
  (verified 22:41 MSK, NRestarts=0).

---

## Sprint 1.3.0 — Capability Router V2 (wrap note)

STATUS_READ enforcement обёрнут за CapabilityRouter (agent/capability_router/):
в режиме `enforce` решение принимается через resolver→registry→policy для
ТОЧНОГО скоупа 1.2.4 — те же 7 subtypes, тот же per-subtype verified tool
контракт (`STATUS_SUBTYPE_TOOLS`; HEALTH/SERVICE/GENERIC под
`STATUS_RUNTIME`), та же READ-ONLY метаданные-проверка, тот же STATUS_READ
allowlist. Tool-эквивалентность точная: decision.tool = per-subtype tool
(например HEALTH_STATUS → `health_status`), max_tool_calls=1.

Shadow-сравнение фиксирует route/tool/reason match для S1-S7 (100%).
`canary_ping` остаётся legacy fallback-поверхностью и не является
маршрутизируемым tool'ом в 1.3.0. Флаг `HERMES_CAPABILITY_ROUTER_V2`
(off|shadow|enforce, default off) независим от `HERMES_INTENT_ROUTER_MODE`;
rollback = flag=false + restart — STATUS_READ enforcement 1.2.0 продолжает
работать.
