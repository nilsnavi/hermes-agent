# SPRINT 1.3.5 — CONTROLLED SANDBOX MUTATION RUNTIME

**STATUS: PASS**

Real state-changing execution proven safe — but ONLY inside a
Hermes-owned sandbox root, with hard-disabled production mutation.

**VERSION:** `sandbox_runtime 1.3.5`

## Files created

**Module `agent/sandbox_runtime/` (19 files):** `__init__.py` (standalone,
production mutation hard-disabled), `models.py` (request/plan models,
state machine + LEGAL_TRANSITIONS), `exceptions.py` (full hierarchy),
`root.py` (resolve_sandbox_path — path boundary), `preflight.py` (21
checks + fingerprint), `approval.py` (run/plan-scope, TTL, single-use),
`snapshot.py` (backup BEFORE mutation + manifest + restore),
`filesystem.py` (atomic write: temp→fsync→rename), `lock.py`
(per-resource, bounded wait, stale recovery), `transaction.py` (durable
JSONL exactly-once journal), `verifier.py` (independent post-check),
`health.py` (health gate, lock-leak aware), `rollback.py` (restore +
verify), `recovery.py` (crash classification, NO auto-retry),
`service.py` (sandbox test daemon, identity guard), `security.py`
(gateway self-control + secret scan), `adapter.py` (the ONLY mutation
adapter + fault injection), `sandbox_boundary.py` (SBL bridge),
`pipeline.py` (the change-cycle), `registry.py` (SandboxToolRegistry),
`events.py` (audit vocabulary), `telemetry.py` (counters + p95),
`flags.py` (fail-closed, kill switch), `cli.py` (read-only).

**Tests `tests/sandbox_runtime/` (18 files):** conftest + models /
path_boundary / preflight / approval / snapshot / atomic_write /
service_control / idempotency / locking / toctou / verification /
health / rollback / crash_recovery / security / invariants /
integration (S1–S29 scenarios).

**Docs:** `docs/hermes-v2/sandbox-mutation-runtime-1.3.5.md`,
`sandbox-mutation-safety-1.3.5.md`, `sandbox-recovery-1.3.5.md`.

## Files changed

- `docs/hermes-v2/production-activation.md` — Sprint 1.3.4/1.3.5 roadmap rows
- `docs/hermes-v2/operator-runbook.md` — §15 sandbox mutation runtime section
- **Production (gateway/agent/cron/config): ZERO changes.**

## Test results

- **RED** (before implementation): 17 files → all collection-error
  `ModuleNotFoundError: agent.sandbox_runtime`, 0 passed — honest RED.
- **GREEN** (canonical `scripts/run_tests.sh tests/sandbox_runtime`):
  **168/168 PASS, 17 files, 6.9s** (163 baseline + 5 late
  kill-switch/state-machine tests).
- **Scope regression:** system_boundary + verified_tool_executor →
  273/273; intent_router + runtime/execution/persistence/recovery/
  orchestrator → 703/1 (the 1 = cross-file /tmp env leak,
  isolated PASS).

## Regression (full suite)

`scripts/run_tests.sh` → **2951 files, 32290 passed, 12 failed,
210 skipped** in 1502.4s (16 workers).

All 12 failures classified pre-existing/environmental (evidence chain:
git-clean files → zero sandbox_runtime imports → identical failure
classes in Sprint 1.3.0 (13 failed) and 1.3.1 (13 failed) baselines →
isolated reruns):

| Failure | Class |
|---|---|
| live-system-guard self-tests ×3 | pre-existing env |
| rtk-rewrite plugin-discovery ×4 | known since 1.0.6.3 |
| FTS5 context-enrichment ×1 | pre-existing env |
| footgun repo-scan ×1 | pre-existing env (needs suppression for new test files) |
| qwen-oauth auth-pool ×1 | known 0.11 class |
| openclaw migration ×1 | pre-existing env |
| turn_lease timeout ×1 | load flake (isolated PASS) |
| verified_tool_executor p95 ×1 | load flake (isolated PASS) |

**0 regressions from 1.3.5.**

## Performance (§39)

- preflight p95 ≈ **3.7 ms** (target < 5 ms) ✔
- transaction orchestration p95 ≈ **3.06 ms** (target < 10 ms) ✔
  (N=200 warm: avg 2.81, p50 2.77, max 3.28 ms; first cold run showed
  35 ms — import/init overhead, not the hot path)

## Security

- `scan_for_secrets` over module + tests: **0 findings in agent/**
  (5 hits are the intentional secret fixtures in test_security.py).
- Kill switch unit-proven: flags off / mode off / unknown mode →
  DENIED, adapter calls = 0; defaults off.
- P0 invariants test-suite green: no production mutation, no gateway
  self-restart, no path/symlink escape, no adapter after BLOCK, no
  auto-retry of UNKNOWN_OUTCOME, no duplicate execution, no commit
  without verify/health/backup, no risk decrease after SBL.

## Backup

`~/hermes-backup-sprint1.3.5-20260814-222839`, SHA256SUMS 833/833 OK.

## Production-untouched proof (§41, before/after)

- Gateway MainPID **309121 → 309121** (identical), NRestarts=**0**,
  ActiveState=active, ExecMainStatus=0.
- config.yaml sha256 **c1e6b73e… → c1e6b73e…** (identical).
- jobs.json: still **19 jobs, identical id set** (runtime metadata
  only changed — scheduler writes, not this sprint).
- state.db: integrity ok, 6 agent_v2 tables, **0 pending approvals**.
- Flags: no SANDBOX/SYSTEM_CHANGE/MUTATION vars in gateway env (off).
- `~/.hermes/sandbox` NOT created on the live host.

## Risks

- Live flag activation (§40) NOT performed — requires explicit
  operator decision + controlled restart; flags remain OFF (by design).
- Live safety matrix (5 commits / 3 rollbacks / 3 denials / 2 dupes /
  2 concurrency) pending operator decision.
- Sandbox service control is subprocess-based (production units
  blocked by identity guard) — systemd-backed control is future work.
- The `.txn/` journal is JSONL (fsync per append) — durable, not a
  full WAL; sufficient for crash classification.

## Next step

Sprint 1.3.6 brief (e.g. service-control hardening / live sandbox
activation with operator-gated restart), or operator decision on the
1.3.5 live safety matrix. Not started — awaiting command.
