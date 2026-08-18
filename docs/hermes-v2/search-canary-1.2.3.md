# Sprint 1.2.3 — SEARCH_READ Controlled Canary

> Date: 2026-08-14 · Hermes Agent 2.0 · Intent Router
> Baseline: Sprint 1.2.2 PASS (verified READ_ONLY `operational_log_search` tool, SEARCH_READ shadow).
> Scope: grant SEARCH_READ a REAL V2_CANARY route for a narrow operational-search allowlist (controlled canary). SEARCH_READ does NOT become globally enforced.

## What was built

### Scoped feature flag (§4)

`HERMES_SEARCH_READ_CANARY` (default **false**) — read per-request from the
environment by `read_router_flags()` (router key `search_canary`). Activated
by drop-in `~/.config/systemd/user/hermes-gateway.service.d/sprint123-search-canary.conf`
(600). STATUS_READ enforcement is INDEPENDENT and unchanged (mode stays
`enforce_status_read`; §17 regression proves no routing drift).

### SearchCanaryPolicy (§6) — `agent/intent_router/enforcement.py`

Pure decision object: `ALLOW_V2_SEARCH` or `LEGACY` with a mandatory deny
reason. Gate ladder (fail closed, unsafe FIRST):

1. policy enabled (§4) → `POLICY_DISABLED`
2. intent == SEARCH_READ (defensive; unsafe never reaches the branch)
3. **mixed unsafe intent** (§7) → `UNSAFE_MIXED_INTENT` — deterministic
   substring scan of the normalized text for write/delete/system/schedule/
   approval action words; unsafe ALWAYS outranks SEARCH_READ
4. **secret query** (§8) → `SECRET_QUERY` — checked BEFORE the allowlist so a
   secret-hunting phrase always reports SECRET_QUERY; tool execution = 0
5. **allowlist** (§9) → `SEARCH_NOT_ALLOWLISTED` — exact §9 phrases (12 RU+EN),
   word-boundary on the NORMALIZED text, never auto-expanded
6. subtype ∈ {log/event/scheduler/provider/integration}_search (§2) →
   `SEARCH_NOT_ALLOWLISTED` (deterministic 1:1 from source)
7. source ∈ {GATEWAY_LOG, EVENTS, SCHEDULER, PROVIDER, INTEGRATION} (§3) →
   `SOURCE_NOT_ALLOWED`
8. capability OPERATIONAL_SEARCH verified → `CAPABILITY_MISSING`
9. tool verified (READ_ONLY + idempotent + no-network contract, §1/§5) →
   `TOOL_NOT_VERIFIED`
10. query valid (normalized, bounded; §10) → `QUERY_INVALID`
11. health == HEALTHY → `HEALTH_UNAVAILABLE`
12. confidence >= 0.7 → `LOW_CONFIDENCE`
13. no ambiguity → `AMBIGUOUS`
14. canary cap (§18) → `CANARY_LIMIT_REACHED` (additive reason)

### Router integration — `agent/intent_router/router.py`

`_search_shadow_eval` → `_search_canary_eval`: identical candidate gate (§15),
then branch on the flag:

- flag **off** → EXACT 1.2.2 shadow behavior (`policy_blocked=True`,
  `SEARCH_SHADOW_ONLY`, actual V2 = 0);
- flag **on** → `SearchCanaryPolicy.decide(...)`; granted → `allowed=True`,
  `actual_route=V2_CANARY`, `eligible_tools=["operational_log_search"]`
  (ONE tool max, §13), exactly ONE response (§11 — the gateway's existing
  enforce path already guarantees no legacy duplicate after TOOL_STARTED).

Outcome gains `search_canary`, `search_subtype`, `search_deny_reason` fields.
§22 metrics: `search_enforcement.{attempts,allowed,blocked,success,failure,
fallback,success_live,success_synthetic,deny_reasons,by_subtype}`.
§19 accounting: only `sample_source == "LIVE"` counts toward the §18 cap
(`SEARCH_CANARY_MAX_SUCCESS = 20`); synthetic never counts.

`record_enforcement_execution` routes search-canary outcomes to the search
bucket and increments live/synthetic success counters (the §18 cap check
reads `search_canary_success_live` at decision time).

### Gateway (minimal, both message paths)

- `gateway/run.py` + `gateway/platforms/api_server.py`: when the outcome is a
  search-canary grant, the single step spec carries `arguments={source,
  limit:10, time_window:"1h"}` (router-derived source). The QUERY arrives via
  `context.goal` (event text[:500], bounded, already router-validated) —
  NEVER in step arguments, so no raw prompt is persisted (§24).
- `agent/gateway_v2/canary.py` `_operational_log_search_handler`: query
  fallback `arguments.query or context.goal` (explicit args win for tests).
- `agent/intent_router/gateway_hook.py`: enforce log line extended with
  `search_canary / search_subtype / deny_reason` (run↔log correlation §21).

### Classifier (minimal, EN canary compounds)

`_SEARCH_READ` += `"hermes events"`, `"mcp errors"` (mirror the RU compounds
«события hermes» / «ошибки mcp») — without them the EN allowlist phrases
classify as `information_read` and the canary can never grant. No existing
dataset case collides (offline eval re-verified, accuracy stays 1.0).

### Models — `agent/intent_router/models.py`

- `SearchDenyReason` enum — the 11 mandatory deny reasons + additive
  `CANARY_LIMIT_REACHED`;
- `SearchSubtype` enum — exactly the 5 verified subtypes (no new subtypes);
- `EnforcementOutcome` += `search_canary / search_subtype / search_deny_reason`.

### Tests (§34) — `tests/intent_router/test_search_canary.py` (24 tests)

All 17 mandatory tests + policy unit checks: C1-C6 allowlist grants per
subtype, secret/filesystem/web/delete/system/schedule negatives, exactly-one
response/tool, empty-result-no-fallback, source-unavailable fail-closed,
duplicate-input idempotency, STATUS_READ unchanged with flag ON, deny-reason
reachability, exact-phrase allowlist, mixed-safe allowlist phrases,
deterministic subtype detection, policy-disabled, 20-live cap,
live/synthetic accounting.

### Dataset (§35)

427 → **446** (12 canary allowlist phrases + 7 negatives). Previous labels
untouched. Offline eval: **accuracy 1.0, class_accuracy 1.0,
read_only_precision 1.0, unsafe_as_read_only 0, unsafe_as_canary 0**.

## Verified numbers (this sprint)

- Scoped enforce-suite (intent_router + operational_search + gateway_v2):
  **40 files / 419 passed / 0 failed**.
- Canonical V2 scope (runtime+execution+persistence+recovery+orchestrator+
  gateway_v2+intent_router+operational_search+model_router+provider_registry+
  integrations): **75 files / 782 passed / 0 failed** (1.2.2: 74/758 — scope
  grew by the new canary test file + dataset cases).
- Full regression: see final report (background, ~27.5k tests).
- Gateway: MainPID 295 (pre) → **6476** (post, 2026-08-14 09:48:54 MSK),
  NRestarts=0. Post-restart evidence rule (§20): ALL live evidence below is
  after MainPID 6476 start.
- Live probes, STATUS_READ regression S1-S7, canary C1-C6 (+3 EN), negatives
  N1-N8 — see final report for per-case numbers.

## Operator invariants (keep)

- `search_enforcement.success_live` <= 20 (§18 cap). At the cap the canary
  stops granting (LEGACY, CANARY_LIMIT_REACHED) — no auto-expansion.
- unsafe V2 = 0; web/filesystem/secret search V2 = 0; tool execution for
  secret queries = 0.
- Auto-disable (§32) if any safety gate trips; rollback = set
  `HERMES_SEARCH_READ_CANARY=false` + `systemctl --user restart hermes-gateway`
  (STATUS_READ stays active — do NOT disable it).

## Files

- Changed: `agent/intent_router/{models,enforcement,router,gateway_hook,
  classifier,dataset_extra}.py`, `agent/gateway_v2/canary.py`,
  `gateway/run.py`, `gateway/platforms/api_server.py`,
  `tests/intent_router/test_search_shadow.py` (contract — see below),
  `docs/hermes-v2/{operator-runbook,production-activation,intent-router-evaluation}.md`.
- New: `tests/intent_router/test_search_canary.py`,
  `docs/hermes-v2/search-canary-1.2.3.md`,
  drop-in `sprint123-search-canary.conf`.
- Pre-change backup: `~/hermes-backup-sprint123-prechange-20260814-093426`
  (864/864 SHA256SUMS OK, state.db integrity ok).
