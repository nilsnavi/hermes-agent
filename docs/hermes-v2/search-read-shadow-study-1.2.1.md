# Sprint 1.2.1 — SEARCH_READ Shadow Study

> Date: 2026-08-13 · Hermes Agent 2.0 · Intent Router
> Status: SHADOW STUDY COMPLETE — SEARCH_READ does NOT have routing authority.

## 1. Goal (§1/§9)

Run a controlled shadow study for SEARCH_READ: classify search
requests, build the candidate V2 decision, record aggregate metrics —
but NEVER route them to V2. The study answers "would SEARCH_READ be
safe to enforce?" with evidence, not guesses.

## 2. Contract (§10) — invariants

- SEARCH_READ actual V2 runs = **0** (hard invariant, asserted in
  tests and checked live)
- No V2 tool execution
- No user-visible V2 response
- Aggregates ONLY — no raw prompts persisted (§12)

## 3. Decision pipeline

For every SEARCH_READ request arriving at the enforcement entry
(`router.enforce` → `_search_shadow_eval`):

1. Classify (unchanged rule-based classifier, SEARCH_READ family).
2. Capability analysis: `CapabilityRegistry.required_for(SEARCH_READ)`
   → SEARCH capability is NOT in the verified V2 surface →
   `missing_capability=True`, `candidate_v2=False`.
3. Policy analysis: SEARCH_READ ∉ enforced intents (§3) →
   `policy_blocked=True`.
4. Outcome: `allowed=False`, block_reason `SEARCH_SHADOW_ONLY`,
   actual_route `LEGACY`. Aggregates recorded in RouterStats.

## 4. Metrics (§9)

| Metric | Meaning |
|---|---|
| search_shadow_total | SEARCH_READ observations |
| search_shadow_candidate_v2 | would-be V2 (capability present) |
| search_shadow_missing_capability | capability gap observed |
| search_shadow_policy_blocked | policy-blocked observations |
| search_shadow_confidence_sum | Σ classifier confidence |
| search_shadow_latency_sum_ms | Σ decision latency |

Exposed via `RouterStats.to_dict()["search_shadow"]`, `router.health()`
and CLI `enforce-suite`.

## 5. Capability study (§12)

For every observation the router records `required capability` /
`available capability` / `candidate tool` / `missing capability` /
`reason blocked` — aggregated only. Current finding: **SEARCH
capability and a search tool are absent from the verified V2 surface;
policy excludes SEARCH_READ from enforcement**. That is the primary
capability gap blocking SEARCH_READ enforcement.

## 6. Sample plan (§11)

- Live: SEARCH_READ observations from the enforced gateway path
  (shadow counters in the gateway process) — 1 live observation in the
  Sprint 1.2.1 activation run (SH1 «search recent scheduler failures»,
  17:40:09 MSK, `SEARCH_SHADOW_ONLY`, candidate_v2=0). The second live
  shadow probe (SH2 «найди последние события Hermes») classified as
  information_read, not SEARCH_READ — recorded as such.
- Synthetic: CLI `enforce-suite` SH1-SH3 cases + test parametrized
  search phrases (suite counter: search_shadow total=4 / candidate_v2=0
  / missing_capability=4 / policy_blocked=4 / actual V2=0).

## 7. Sample limit (§21) — applies to STATUS_READ enforcement only

Initial live enforced STATUS_READ expansion: max 50 enforced runs;
if all green, leave enabled. SEARCH_READ has NO sample limit — it is
never enforced.

## 8. Gate to Sprint 1.2.2

- If shadow evidence is strong (capability gap closed, decision
  quality high): **SPRINT 1.2.2 — SEARCH_READ CONTROLLED CANARY**
- Otherwise: **SPRINT 1.2.2 — SEARCH CAPABILITY HARDENING**
  (add a verified READ_ONLY search tool, e.g. local log scan, then
  re-run the shadow study)

## 9. Result

Sprint 1.2.1 shadow study completed (2026-08-13):

- **Observations**: 1 live (SH1, 17:40:09 MSK) + 3 synthetic in
  enforce-suite = 4 total; SH2 classified information_read (noted).
- **search_shadow_total=4, candidate_v2=0, missing_capability=4,
  policy_blocked=4, confidence_sum=3.6, actual V2 runs=0** — invariant
  §10 held: no V2 tool execution, no user-visible V2 response.
- **Capability gap confirmed**: SEARCH capability/tool ∉ verified V2
  surface; SEARCH_READ ∉ enforced intents (policy block). Shadow
  decision quality is structurally honest but the gap is open.
- **Verdict: NOT READY for controlled canary.** Evidence is
  insufficient — 4 observations (1 live) do not meet the §11 sample
  bar, and the capability gap (a verified READ_ONLY search tool) is
  still open.
- **Gate to Sprint 1.2.2**: SEARCH CAPABILITY HARDENING (add verified
  READ_ONLY local log-scan tool → re-run shadow study → re-evaluate).
