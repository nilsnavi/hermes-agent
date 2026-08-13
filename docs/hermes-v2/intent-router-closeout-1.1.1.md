# Sprint 1.1.1 — Closeout: Intent Router Production OBSERVE Calibration

**Stage:** PRODUCTION OBSERVE · **Date:** 2026-08-13 · **Host:** LXC hermes-agent-1
**Status:** ✅ DONE — observe active, safety green, all gates passed

## 1. What shipped

| Item | Change |
|---|---|
| `agent/intent_router/models.py` | New enums `SampleSource`, `ActualRoute`; decision fields §9–11 (`actual_route`, `sample_source`, `mismatch_class`, `expected_side_effect`, `observation_id`, `policy_gate*`) |
| `agent/intent_router/events.py` | `router_event_payload` extended with §9 fields (backward-compatible defaults) |
| `agent/intent_router/router.py` | Fail-closed `parse_mode` (§6: ENFORCE/SHADOW_DECISION → OFF); `observe()` with `actual_route`/`sample_source`; `RouterStats`; `health()` with p50/p95 ring (§14); `_ACTUAL_TO_EFFECTIVE` mapping |
| `agent/intent_router/gateway_hook.py` | **NEW** — sole gateway↔router bridge (200+ lines): lazy singleton, fail-open, `_pid_health()` probe, `_V2_TO_ACTUAL` mapper, `observe_metrics()`, `router_health()` |
| `gateway/run.py` | Observe hook updated (§57 → §7): thin call into `gateway_hook.observe_gateway_event` |
| `agent/intent_router/cli.py` | New `health` subcommand (`--json`), operator-facing |
| `tests/intent_router/test_observe_calibration.py` | **NEW** — 22 tests covering §6/§7/§8/§9/§10/§11/§12/§13/§14/§32/§40 |

Gateway hook is **non-authoritative by construction**: `actual_route` comes
from `V2Decision` routing state (`_V2_TO_ACTUAL`), never from response text
(§11). The hook is inert (returns `None`, zero overhead) when flags are off.

## 2. Production activation

Flags injected via systemd drop-in (config.yaml untouched):

```ini
# ~/.config/systemd/user/hermes-gateway.service.d/sprint111-observe.conf
[Service]
Environment="HERMES_INTENT_ROUTER_ENABLED=true"
Environment="HERMES_INTENT_ROUTER_MODE=observe"
```

Verified in the running process (`/proc/<pid>/environ`, live):
`HERMES_INTENT_ROUTER_ENABLED=true`, `HERMES_INTENT_ROUTER_MODE=observe`.
NRestarts=0 (controlled restart). Code defaults stay `enabled=false,
mode=off` — no auto-enable.

## 3. Required closeout evidence

### 3.1 Intent accuracy (offline, frozen Sprint 1.1.0 classifier)

| Metric | Value |
|---|---|
| Overall accuracy | **1.0** (382/382) |
| RU accuracy | 1.0 (210/210) |
| EN accuracy | 1.0 (172/172) |
| Class accuracy | 1.0 |
| Unknown rate | 7.07% (27/382) |

### 3.2 Safety (ALL MUST BE 0 — all are 0)

| Counter | Value |
|---|---|
| WRITE/DELETE/SYSTEM/UNKNOWN → recommended CANARY | **0** |
| `unsafe_as_canary` | **0** |
| `unsafe_as_read_only` | **0** |
| `unsafe_predicted_read_only` | **0** |
| Read-only precision | 1.0 |
| Read-only false positive rate | 0.0 |
| Canary candidate rate | 0.0 |

### 3.3 Execution authority audit (static, §30)

`agent/intent_router/` exposes no `execute`/`run`/`resume`/`decide_gateway`/
`modify_request` surface; no tool calls, orchestrator run/resume, provider
calls, or `state.db` writes for ordinary observed requests (asserted by
tests + audit). Production `state.db`: integrity OK, FK 0 violations,
freelist ~55% (**not repaired** — flagged, per brief §4 note).

### 3.4 Gateway / flag / actual-route changes

- Gateway hook: `gateway/run.py` observe call updated to route through
  `gateway_hook.py` (was inline §57 hook — pre-existing, previously inert).
- No routing authority change: actual routing remains legacy; router only
  observes (verified by O1–O10: `effective=legacy` on every case).
- Config.yaml: **untouched** by this sprint (flags via drop-in only).
- Scheduler / provider routing: unchanged.

### 3.5 Performance (§21 — target p95 < 5ms)

| Metric | Value |
|---|---|
| Hook p95 | **1.66 ms** (incl. safe log line) |
| Router-internal p95 | ≈ 0.07 ms |
| Cold start (first call) | **48 ms** (after `_pid_health()` replacement; was 3.4 s with `OperationsService.health()`) |

### 3.6 Live observations (production API server, O1–O10)

10 requests through `127.0.0.1:8642/v1/chat/completions` — all observed,
classified, and logged; 0 router errors. Observed intents: status_read,
system_action, schedule_action, unknown, delete_action, write_action,
conversation, search_read. Safety-relevant: delete_action → candidate
`deny` (not canary) ✓; system_action → `require_approval` ✓;
schedule_action → `require_approval` ✓; unknown → `legacy` ✓.
All `effective=legacy`, all `matched` where production policy aligns.

Hourly watchdog job created: **Intent Router OBSERVE — hourly check**
(`router_observe_watchdog.py`, no_agent, silent-on-OK / alert-on-fail) —
checks service state, live process flags, CLI health, and journald error
path. First run OK.

### 3.7 Test gates

| Gate | Result |
|---|---|
| Full scope (runtime/execution/persistence/recovery/orchestrator/gateway_v2/operations_v2/intent_router) | **78 files, 670 tests passed, 0 failed** |
| New `test_observe_calibration.py` | 22/22 passed |
| Offline evaluation | 382/382, accuracy 1.0, safety PASS |
| Backup (pre-change, §4) | `~/hermes-backup-sprint1.1.1-production-observe-20260813-092628` — **748/748 SHA256 OK** (incl. manual `code/v2-modules.tar.gz`) |

## 4. Rollback triggers watched (§39) — hourly watchdog

- unsafe CANARY recommendation > 0
- actual route changed because of the router
- secret telemetry leak
- router error rate > 5%
- p95 > 20 ms sustained
- gateway instability / NRestarts growth

Watchdog: `~/.hermes/scripts/router_observe_watchdog.py` (hourly cron,
deliver origin). Manual: `venv/bin/python -m agent.intent_router.cli health
--json` → HEALTHY (unsafe=0, error_rate 0.0, mode=observe).

## 5. Known findings / notes

1. **DB freelist ~55%** — not repaired (out of scope, flagged for ops).
2. **Production observation counters are in-process** (ring + process-wide
   counters in the gateway); CLI `health` in a separate process reports
   per-run zero observations by design. The hourly watchdog therefore
   checks liveness/flags/journald externally — documented in the script.
3. **Rule-freeze (§24)** honored: zero classifier rule changes; only
   telemetry/schema/hook/CLI additions.
4. Config-writer regression §32: covered by the WebUI hardened writer suite
   (`hermes-webui/tests/test_sprint1064_config_persistence.py`, 10 tests,
   patch-only+merge+backup+0600) — Sprint 1.0.6.4 scope; mirrored in
   `test_observe_calibration.py::test_config_writer_preserves_sections_on_flag_update`.

## 6. Next

**Sprint 1.2.0 — Controlled Intent Routing Enforcement** (if safety stays
green and sample sufficient) or **1.1.2 — Calibration Hardening**.
