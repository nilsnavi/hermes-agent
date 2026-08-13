# Operator Runbook — Hermes V2 Operations

Sprint 1.1.1 · Applies to Read-Only Canary + Intent Router OBSERVE.
No secrets in this doc.

All commands read from the default V2 database (`state.db`). Add `--db PATH`
to point elsewhere. All commands are **read-only by default**; mutation
commands require `--confirm`.

## 1. Check health

```bash
python -m agent.operations_v2.cli health
python -m agent.operations_v2.cli health --json     # for automation
```

Look at `status` (healthy / degraded / unhealthy) and `findings` (structured
alert codes). Verify: `gateway_alive`, `db_integrity_last_known`,
`read_only_enforced`, SLO counters all at expected values.

## 2. List V2 runs

```bash
python -m agent.operations_v2.cli runs                     # recent 50
python -m agent.operations_v2.cli runs --status failed
python -m agent.operations_v2.cli runs --status waiting_approval
python -m agent.operations_v2.cli runs --limit 200 --json
python -m agent.operations_v2.cli runs --from 2026-08-11T00:00:00 --to 2026-08-12T00:00:00
```

Filters: `--status`, `--task-type`, `--from`, `--to`, `--limit` (default 50,
max 500). No prompt-body search.

## 3. Inspect a run

```bash
python -m agent.operations_v2.cli run <run_id>             # safe summary
python -m agent.operations_v2.cli timeline <run_id>        # ordered event timeline
```

Summaries carry no raw payloads — only status, counts, hashes and timestamps.

## 4. View approvals

```bash
python -m agent.operations_v2.cli approvals                # pending
python -m agent.operations_v2.cli approval <approval_id> --run-id <run_id>
```

Shows task type, tool, side effect, risk, reason, created/expires at. No raw
prompt/arguments/secrets.

## 5. Approve / reject safely

```bash
# Inspect first — dry run shows the exact transition, zero writes:
python -m agent.operations_v2.cli approve <approval_id> --run-id <run_id> --operator <you> --dry-run

# Real decision (requires --confirm):
python -m agent.operations_v2.cli approve <approval_id> --run-id <run_id> --operator <you> --confirm [--expected-version N] [--note "short note"]
python -m agent.operations_v2.cli reject  <approval_id> --run-id <run_id> --operator <you> --confirm
```

Rules:

- `--run-id` is mandatory — approvals are run-scoped.
- `--confirm` is mandatory — no accidental Enter-to-approve.
- Approving a write/irreversible request is DENIED by policy regardless.
- Approving a cancelled or expired approval is DENIED.

## 6. Inspect manual reviews

```bash
python -m agent.operations_v2.cli manual-reviews
python -m agent.operations_v2.cli manual-reviews --json
```

The queue is reconstructed from durable events — it survives restarts.
Inspection only in this sprint; operator resolution comes later.

## 7. Stale runs

```bash
python -m agent.operations_v2.cli stale-runs
```

Detects runs stuck past threshold (e.g. stale approval, stale RUNNING).
Marked `STALE_RUN`. Never auto-fixed.

## 8. Metrics

```bash
python -m agent.operations_v2.cli metrics                 # last 24h
python -m agent.operations_v2.cli metrics --window 1h
python -m agent.operations_v2.cli metrics --window all
```

## 9. Disable canary (kill switch)

Canary is never auto-disabled. To disable, from a shell **outside** the
gateway process:

```bash
# 1. set HERMES_RUNTIME_V2_CANARY=false in the gateway environment
# 2. restart the gateway externally:
systemctl --user restart hermes-gateway.service
```

Do NOT restart the gateway from inside the gateway process — SIGTERM
propagates to child processes and kills the command mid-flight.

## 10. Disable all V2

```bash
# set HERMES_RUNTIME_V2_ENABLED=false (+ shadow/canary/persistence false)
# restart gateway externally (see step 9)
```

## 11. Verify after restart

```bash
python -m agent.operations_v2.cli health --json
# expect: gateway_alive=true, read_only_enforced per flags, no new findings
```

Check `last_successful_canary_at` / `last_failed_canary_at` and SLO counters
(`write_executions: 0`, `duplicate_responses: 0`, `secret_findings: 0`,
`db_locks: 0`).

## 12. Intent Router health (Sprint 1.1.1)

```bash
python -m agent.intent_router.cli status --json
python -m agent.intent_router.cli health --json
```

Health levels: HEALTHY (unsafe=0, error_rate < 1%, p95 < 5ms) /
DEGRADED / UNHEALTHY. Safety counters that MUST stay 0:
`unsafe_canary_recommendations`, `unsafe_predicted_read_only`.
Observed per-request log lines: `gateway.intent_router.observe …`
(safe fields only — never the prompt).

## 13. Disable Intent Router observe (rollback)

```bash
# 1. flip the flag off (or delete the drop-in):
#    ~/.config/systemd/user/hermes-gateway.service.d/sprint111-observe.conf
# 2. external restart:
systemctl --user daemon-reload && systemctl --user restart hermes-gateway.service
```

With the router off, production behavior is byte/semantically equivalent
(flags default false; hook inert). Legacy/canary/shadow keep running
exactly as before.

## 14. Router incident procedure

1. `HERMES_INTENT_ROUTER_ENABLED=false` (drop-in).
2. External restart.
3. Verify: `health` shows disabled, `gateway.intent_router.observe`
   lines stop, ordinary traffic unchanged.
4. Collect evidence (metrics, O-cases, log lines).
5. Report before re-enabling.

Immediate triggers: unsafe CANARY recommendation > 0, actual route
changed by router, duplicate response, secret telemetry leak, gateway
instability, memory/thread/fd leak, error rate > 5%, p95 > 20ms
sustained, unexpected provider/scheduler/tool behavior.
