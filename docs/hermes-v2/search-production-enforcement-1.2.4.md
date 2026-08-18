# Sprint 1.2.4 — SEARCH_READ Limited Production Enforcement

> Date: 2026-08-14 · Hermes Agent 2.0 · Intent Router
> Baseline: Sprint 1.2.3 PASS (SEARCH_READ controlled canary stable, 9/9 live, 60m window).
> Scope: move SEARCH_READ from controlled canary to LIMITED PRODUCTION ENFORCEMENT —
> a scoped production V2 route for the SAME narrow operational-search use cases.
> NO global rollout. STATUS_READ enforcement is untouched (§5).

## What was built

### Scoped mode selector (§4) — `HERMES_SEARCH_READ_MODE`

Replaces the boolean canary flag as the master selector. Values:

| value | behavior |
|---|---|
| `off` | policy DISABLED — SEARCH_READ routes LEGACY with `POLICY_DISABLED`, NO shadow/prod metrics collected (stricter than shadow; unknown values fail closed HERE) |
| `shadow` | EXACT Sprint 1.2.2 study — actual route always LEGACY, `search_shadow_*` metrics |
| `canary` | EXACT Sprint 1.2.3 behavior — `V2_CANARY` route, cap 20 live, `search_canary=True` |
| `limited_enforce` | **NEW (this sprint)** — production route `V2`, cap 50 live (§11), `search_prod=True` |

- Unknown/absent-invalid value → **fail closed to `off`** (§4).
- `HERMES_SEARCH_READ_MODE` absent → falls back to the Sprint 1.2.3 flag
  (`HERMES_SEARCH_READ_CANARY=true` → canary), else `shadow` (the pre-1.2.3 default).
- Parsing: `parse_search_mode()` in `agent/intent_router/router.py`; resolution
  `_resolve_search_mode(flags)` (explicit `search_mode` wins, legacy bool → canary/shadow,
  bare default → shadow).

### SearchProductionPolicy (§1-§16) — `agent/intent_router/enforcement.py`

Pure decision object mirroring the canary policy: `ALLOW_V2_SEARCH` (route `V2`, §9) or
`LEGACY` with a mandatory deny reason (§16). The gate ladder is SHARED with the canary
policy via `_search_gate_ladder()` (same order, same deny reasons — contract-tested by both
test files). Differences from canary: `VERSION="search-prod-v1"`, cap reason
`SEARCH_LIMIT_REACHED` (canary keeps `CANARY_LIMIT_REACHED`), allowed code
`search_prod_allowed` (canary `search_canary_allowed`).

§16 block reasons (all reachable): SEARCH_NOT_ALLOWLISTED · SOURCE_NOT_ALLOWED ·
CAPABILITY_MISSING · TOOL_NOT_VERIFIED · LOW_CONFIDENCE · AMBIGUOUS · SECRET_QUERY ·
UNSAFE_MIXED_INTENT · HEALTH_UNAVAILABLE · QUERY_INVALID · POLICY_DISABLED ·
+ SEARCH_LIMIT_REACHED (additive, §11 cap).

### LIVE allowlist (§12) — `SEARCH_PROD_ALLOWLIST`

The brief's own 12 "initial production phrases" — **NOT identical** to the canary list
(3 RU phrases differ: «покажи последние события Hermes», «покажи последние ошибки
provider», «покажи ошибки MCP»). Exact-phrase word-boundary matching on the NORMALIZED
text; NO auto-expansion. 9 of 12 overlap with the canary list; both lists are pinned at 12.

### §15 observability — `search_prod_*` counters

`attempts, allowed, blocked, success, failure, fallback, empty` — by subtype AND source,
plus `deny_reasons`, `success_live` / `success_synthetic` (only LIVE counts toward the
§11 cap of 50). `empty` = granted V2 run COMPLETED with 0 matches (§13 — valid success,
never legacy fallback); the gateway detects it via
`gateway_hook.detect_empty_enforce_result(resp)` and reports it through
`record_enforcement_result(..., empty=...)`.

### Mixed intent / secret / web / filesystem (§6-§8)

Unchanged safety contract: unsafe intent ALWAYS wins (delete/system/schedule/write →
intent gate → LEGACY); `SECRET_QUERY` never reaches the tool (execution = 0);
web/filesystem search is never `operational_log_search`.

## Files changed

- `agent/intent_router/models.py` — `SearchDenyReason.SEARCH_LIMIT_REACHED`;
  `EnforcementOutcome.search_prod` / `search_mode` fields (+to_dict).
- `agent/intent_router/enforcement.py` — `_search_gate_ladder()` (shared),
  `SEARCH_PROD_MAX_SUCCESS=50`, `SEARCH_PROD_ALLOWLIST`, `search_prod_allowlist_matches`,
  `SearchProductionPolicy`; `SearchCanaryPolicy.decide` now delegates to the shared ladder
  (behavior-identical, all old tests green).
- `agent/intent_router/router.py` — `HERMES_SEARCH_READ_MODE` parse + `_resolve_search_mode`,
  mode dispatch (off/shadow/canary/limited_enforce) in `_search_canary_eval`,
  `search_prod_*` counters (§15), `record_enforcement_execution(..., empty=)` + prod branch,
  `_act_bucket("V2")`, shadow metrics now shadow-mode-only.
- `agent/intent_router/gateway_hook.py` — enforce-log `search_prod=`/`search_mode=` fields,
  `record_enforcement_result(..., empty=)`, `detect_empty_enforce_result()`.
- `gateway/run.py` + `gateway/platforms/api_server.py` — search step args for
  `search_prod` outcomes (same as canary), empty-result reporting.
- `agent/intent_router/dataset_extra.py` — 11 new §12/§23 offline cases.
- `tests/intent_router/test_search_prod.py` — NEW: mode parse, §12 list split, all §16
  deny reasons, §11 cap (live-only), §15 metrics by subtype/source, empty-accounting,
  §17 STATUS_READ regression, §23 negatives.
- `docs/hermes-v2/search-production-enforcement-1.2.4.md` — this document.

## Activation

Drop-in `~/.config/systemd/user/hermes-gateway.service.d/sprint124-search-prod.conf`
(600): `HERMES_SEARCH_READ_MODE=limited_enforce`. The Sprint 1.2.3 canary drop-in
(`HERMES_SEARCH_READ_CANARY=true`) stays in place — the mode env supersedes it when
present; removing/editing the 1.2.4 drop-in falls back to canary.

## Rollback (§32)

- `HERMES_SEARCH_READ_MODE=canary` (or `shadow`) in the drop-in + restart → instant
  rollback to canary (or the study).
- Or remove `sprint124-search-prod.conf` + restart → falls back to the 1.2.3 canary flag.
- STATUS_READ is never disabled for a search-only problem (§26).

## Verified numbers (this sprint)

- intent_router suite: **143/143 passed / 0 failed** (test_search_prod 36 +
  test_search_canary + shadow + enforcement + status_expansion).
- Scoped canonical (intent_router + gateway_v2 + operational_search):
  **41 files / 455 passed / 0 failed**.
- Full regression: **2907 files / 31758 passed / 11 failed / 210 skipped**.
  The 8 failing files have EMPTY git-diff (same 11 pre-existing as 1.2.3 —
  hermes_cli plugin discovery, FTS5, live-system-guard self-tests, turn_lease).
- Offline eval §27: **457 cases, accuracy 1.0, class_accuracy 1.0,
  read_only_precision 1.0, unsafe_as_read_only 0, unsafe_as_canary 0**.
- Gateway: MainPID chain 222852 (11:48:25, controlled activation) →
  224108 (11:54:45) → **227036 (12:02:51)**, NRestarts=0, both later restarts
  caused by the LEGACY agent executing the N5 «перезапусти gateway» probe
  (system_action → intent gate → LEGACY; system routed V2 = 0). Post-restart
  evidence rule (§20): ALL live evidence below is after MainPID 227036 start.
- Live probes, 2 rounds (§22): S1-S7 → 200 route=V2_CANARY 7/7 per round;
  P1-P12 → 200 route=V2 (tool=operational_log_search, policy=search-prod-v1)
  12/12 per round = **24 live V2 search runs** (cap 50, §11); negatives N1-N8
  blocked — per round 1×SECRET_QUERY + 2×SEARCH_NOT_ALLOWLISTED +
  5×INTENT_NOT_ALLOWED (LEGACY).
- state.db: 24 search runs, each 1 plan / 1 step / 1 TOOL_STARTED +
  1 TOOL_COMPLETED (duplicates 0); goals = probe texts; step args contain only
  limit/source/time_window (raw query never persisted); integrity_check ok,
  foreign_key_check 0, orphans 0, WAL, no locks; approvals 1 (pre-existing
  ops-drill, 2026-08-11).
- Performance: total response p50 130 ms / p95 170 ms; router duration_ms
  p50 0.73 ms / p95 2.9 ms; tool execution p50 0.9 ms / p95 11.8 ms.
- Stability window 60m (12:02:51 → 13:02:51): snapshots 5/15/30/60 — all
  MainPID 227036, NRestarts=0, log errors=0, RSS 184→192 MB.
- Auto-disable §26: system routed V2 = 0, unsafe predictions = 0, duplicate
  tool calls = 0, duplicate responses = 0, DB locks = 0.

## Operator invariants (keep)

- `search_prod.success_live` <= 50 (§11 cap). At the cap production stops
  granting (LEGACY, SEARCH_LIMIT_REACHED) — no auto-expansion. Synthetic and
  empty-result runs never count toward the cap (§19).
- unsafe V2 = 0; web/filesystem/secret search V2 = 0; tool execution for
  secret queries = 0 (SECRET_QUERY → LEGACY with execution 0).
- Auto-disable (§26) if any safety gate trips; rollback = mode back to
  canary/shadow + restart (STATUS_READ stays active — do NOT disable it).

## Auto-disable conditions (§26)

Any of: unsafe V2 > 0 · secret tool execution > 0 · filesystem escape > 0 ·
network execution > 0 · shell execution > 0 · duplicate response > 0 ·
duplicate tool call > 0 · DB lock regression · gateway instability ·
search failure rate > 5% after >= 20 runs → set mode back to canary/shadow + restart.
STATUS_READ stays active.

---

## Sprint 1.3.0 — Capability Router V2 (wrap note)

Sprint 1.3.0 оборачивает SEARCH_READ production-политику за
CapabilityRouter (agent/capability_router/): в режиме `enforce` решение для
SEARCH_READ принимается через resolver→policy с ТЕМ ЖЕ verified-контрактом —
общая gate-лестница `_search_gate_ladder` (policy.py вызывает
`search_prod_allowlist_matches`, `validate_query`, `is_secret_query`,
`has_mixed_unsafe_intent`, `SEARCH_ALLOWED_SOURCES`), тот же 12-фразовый
allowlist, тот же cap 50 live (`SEARCH_PROD_MAX_SUCCESS`), те же deny
reasons. Route/tool/reason эквивалентность 100% (корпус P1-P12 + N1-N8).

Важно: capability router НЕ имеет authority вне `limited_enforce` — при
`HERMES_SEARCH_READ_MODE=canary/shadow/off` решение остаётся за legacy-путём
(поведение 1.2.3/1.2.2 сохранено байт-в-байт). Флаг
`HERMES_CAPABILITY_ROUTER_V2` (off|shadow|enforce, default off) не влияет на
`HERMES_SEARCH_READ_MODE`. Rollback capability router: flag=false + restart
(§48) — production-политика 1.2.4 продолжает работать.
