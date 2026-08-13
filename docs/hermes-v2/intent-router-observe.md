# Intent Router — Production OBSERVE Calibration (Sprint 1.1.1)

> Stage: **PRODUCTION OBSERVE** (2026-08-13) · Mode guard: OFF/OBSERVE only ·
> ENFORCE and SHADOW_DECISION are not implemented and fail closed to OFF.
> Hard safety rule (§1): **actual_route MUST NOT depend on the router.**

## 1. Activation

Flags are injected via systemd drop-in
`~/.config/systemd/user/hermes-gateway.service.d/sprint111-observe.conf`
and take effect on a **controlled external restart**:

```ini
[Service]
Environment="HERMES_INTENT_ROUTER_ENABLED=true"
Environment="HERMES_INTENT_ROUTER_MODE=observe"
```

Code defaults remain `enabled=false, mode=off` — there is NO auto-enable.
The gateway hook (`gateway/run.py` → `agent/intent_router/gateway_hook.py`)
is inert (zero overhead, returns immediately) when the flags are unset.

## 2. Router contract (what observe does / does not do)

The router **does**:

- read the request context (lexical families + token bucket only),
- classify the intent (deterministic, no LLM, no network),
- compute risk / expected side effect / candidate + effective route,
- compare its recommendation with the **actual** route (from gateway
  routing state — `V2Decision` — never from response text),
- write **safe telemetry only** (in-memory bounded ring + one log line).

The router **never**:

- changes the actual route (LEGACY/CANARY/SHADOW are decided before it),
- executes tools, calls the orchestrator, resumes runs,
- changes the response, provider, or scheduler,
- writes rows to `state.db` for ordinary observed requests.

Any router exception increments `router_errors`, logs one safe line and
the request proceeds normally on its already-decided route (§8).

## 3. Mode guard (§6)

`agent/intent_router/router.py::parse_mode` maps both `ENFORCE` and
`SHADOW_DECISION` to `OFF`. Garbage/absent values → `OFF`. There is no
enforcement path in this sprint.

## 4. Safe telemetry schema (§9)

Persisted/logged fields only:

```
request_id, intent, risk, expected_side_effect, candidate_route,
effective_route, actual_route, confidence_bucket, reason_codes,
required_capability_count, missing_capability_count, matched,
router_version, policy_version, duration_ms, sample_source, mode
```

NEVER persisted: raw prompt, raw user message, Authorization, cookies,
tokens, attachment content, raw tool args, full metadata.

Sample source enum (§10): `LIVE`, `INTERNAL_SYNTHETIC`,
`EXPLICIT_CANARY`, `EXPLICIT_SHADOW` — metrics keep them separate.

Actual route enum (§11): `LEGACY`, `V2_CANARY`, `SHADOW`, `OPERATIONS`,
`OTHER`.

## 5. Metrics (§12-13)

| Metric | Source |
|---|---|
| `router_observations_total` | process-wide counter |
| `router_errors` | process-wide counter |
| `router_matches` | recommendation == actual |
| `router_policy_mismatches` | recommendation != actual (expected while production policy stays legacy) |
| `router_classification_reviews` | operator-reviewed observations |
| `recommended_{legacy,shadow,canary,approval,deny}` | per-decision |
| `actual_{legacy,canary,shadow}` | per-decision actual route |

Safety-critical counters (ALL MUST stay 0):

- WRITE/DELETE/SYSTEM/UNKNOWN → recommended `V2_CANARY`
- `unsafe_predicted_read_only`

If any exceeds 0: disable observe immediately (`ENABLED=false` +
external restart) — actual routing remains unaffected by construction.

## 6. Health (§14)

```bash
venv/bin/python -m agent.intent_router.cli health --json
```

| Level | Condition |
|---|---|
| HEALTHY | unsafe=0, error_rate < 1%, p95 < 5ms |
| DEGRADED | latency/error warning |
| UNHEALTHY | unsafe recommendation > 0 (or router altered route — impossible by construction) |

p50/p95 are computed from the in-memory ring (bounded, no persistence).
Production target: **p95 < 5 ms** (measured 1.1.1: p95 ≈ 1.7 ms incl.
log line; router-internal p95 ≈ 0.07 ms).

## 7. Operator commands

```bash
# observe one synthetic request (in-memory only, nothing persisted)
venv/bin/python -m agent.intent_router.cli classify --text "покажи статус" --json
# offline evaluation (382-case dataset)
venv/bin/python -m agent.intent_router.cli evaluate --json
# router status / health
venv/bin/python -m agent.intent_router.cli status --json
venv/bin/python -m agent.intent_router.cli health --json
```

## 8. Rollback (§38)

```bash
# 1. remove flags (or set ENABLED=false / MODE=off) in the drop-in
rm ~/.config/systemd/user/hermes-gateway.service.d/sprint111-observe.conf
# 2. controlled EXTERNAL restart (never from inside the gateway process)
systemctl --user daemon-reload
systemctl --user restart hermes-gateway.service
```

Legacy / canary / shadow behavior is byte-equivalent with the router off
(verified by equivalence tests §28 and the O1–O10 run).

## 9. Immediate rollback triggers (§39)

- unsafe CANARY recommendation > 0
- actual route changed because of the router
- duplicate user response
- secret telemetry leak
- gateway instability / memory/thread/fd leak
- router error rate > 5%
- p95 > 20 ms sustained
- unexpected provider/scheduler/tool behavior

## 10. Incident procedure

1. Disable the flag (`HERMES_INTENT_ROUTER_ENABLED=false`).
2. External restart.
3. Verify: `router_health` disabled, `gateway.intent_router.observe`
   log lines stop, ordinary traffic unchanged.
4. Collect the observation evidence (ring metrics, log lines, O-cases).
5. Report before re-enabling.

## 11. Rule-freeze policy (§24)

Classifier rules from Sprint 1.1.0 are frozen. A rule change requires:

- 3+ independent live examples,
- same root cause,
- systematic misclassification,
- safety dataset remains 382/382 after the fix.

Otherwise record a calibration finding only.

## 12. Stage status

| Item | Status (2026-08-13) |
|---|---|
| Router | enabled=true, mode=observe (production) |
| Routing authority | 0 (observer only) |
| Offline evaluation | 382/382, accuracy 1.0 |
| Safety leakage (WRITE/DELETE/SYSTEM/UNKNOWN → CANARY) | 0 |
| `unsafe_predicted_read_only` | 0 |
| Config.yaml | untouched by this sprint (flags via systemd drop-in) |
| Scheduler / provider routing | unchanged |

Next: **Sprint 1.2.0 — Controlled Intent Routing Enforcement** (if
safety green + sufficient sample) or **Sprint 1.1.2 — Calibration
Hardening**.
