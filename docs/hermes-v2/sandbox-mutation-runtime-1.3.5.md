# Sandbox Mutation Runtime — Sprint 1.3.5

> Hermes Agent 2.0 · module `agent/sandbox_runtime/` · 2026-08-14
> Baseline: Sprint 1.3.4 (Transactional System Change Pipeline) PASS

## What this sprint proves

Sprint 1.3.5 implements the **Controlled Sandbox Mutation Runtime**: a
full state-changing change-cycle (REQUEST → CLASSIFY → CAPABILITY →
POLICY → BOUNDARY → PLAN → PREFLIGHT → APPROVAL → SNAPSHOT → LOCK →
EXECUTE → VERIFY → HEALTH → COMMIT) that executes **real mutations**,
but ONLY inside a Hermes-owned sandbox root.

Production mutation is **impossible by construction**:
- the only executable targets resolve inside the sandbox root
- every real change requires approval + snapshot + lock + verification
  + health + commit
- `HERMES_SANDBOX_MUTATION_V2_ENABLED` defaults to false (kill switch)

## Architecture

```
agent/sandbox_runtime/
  __init__.py          package + version 1.3.5
  models.py            SandboxMutationRequest/Plan, operation & state enums
  exceptions.py        full error hierarchy (SandboxPathEscape, ...)
  root.py              SandboxRoot + resolve_sandbox_path (path boundary)
  preflight.py         21-check preflight + fingerprint
  approval.py          run/plan-scoped, TTL-bound, single-use approvals
  snapshot.py          per-operation backup + SHA256SUMS + restore
  filesystem.py        atomic_write (temp → fsync → rename)
  service.py           sandbox test service (subprocess daemon)
  lock.py              per-resource locks + process-local serialization
  transaction.py       durable exactly-once journal (.txn/)
  verifier.py          independent post-execution verification
  health.py            health gate (fs, orphans, leaks, locks)
  rollback.py          snapshot restore + rollback verification
  toctou.py            fingerprint re-check before execution
  recovery.py          crash classification + transaction scanner
  security.py          gateway self-control guard + secret scan
  adapter.py           the ONLY sanctioned mutation adapter + fault injection
  sandbox_boundary.py  SystemBoundaryLayer bridge (mandatory)
  pipeline.py          SandboxMutationPipeline (the change-cycle)
  registry.py          SandboxToolRegistry (verified mutation surface)
  events.py            SANDBOX_* audit vocabulary
  telemetry.py         counters + latency p95
  flags.py             feature flags (off/shadow/sandbox, fail-closed)
  cli.py               read-only operational CLI
```

## Pipeline (happy path)

1. kill switch check → DENIED if flags off
2. request model validation (unknown fields/operations → DENY)
3. request TTL check
4. exactly-once replay (prior COMMITTED/ROLLED_BACK → replay,
   UNKNOWN_OUTCOME → MANUAL_REVIEW_REQUIRED)
5. path resolution (`resolve_sandbox_path`, §4) — escape → DENY
6. gateway self-control guard (§16/§33) — hermes-gateway always BLOCK
7. SystemBoundaryLayer gates (preflight/authorize, §17)
8. plan creation (immutable after approval, §7)
9. preflight (21 checks, §8) + fingerprint (§9)
10. approval (run-scoped, plan-scoped, single-use, TTL, §10)
11. snapshot/backup BEFORE mutation (§11) — BACKUP_FAILED → adapter=0
12. lock (per-resource, bounded wait, §14)
13. TOCTOU second fingerprint check (§26) — mismatch → adapter=0
14. execute (the ONLY adapter call, §18)
15. independent verification (§19) — adapter result is NOT proof
16. health gate (§20)
17. commit (§21) — only after success+verify+health

## Failure path

Any failure → FREEZE further mutations → rollback from snapshot →
verify rollback → health → ROLLED_BACK. Rollback never hides the
original failure; the audit carries both reasons
(`original_failure` + `rollback_status`). Rollback verification failure
→ MANUAL_REVIEW_REQUIRED.

## Feature flags

| Flag | Default | Meaning |
|---|---|---|
| `HERMES_SANDBOX_MUTATION_V2_ENABLED` | `false` | master gate |
| `HERMES_SANDBOX_MUTATION_V2_MODE` | `off` | `off`/`shadow`/`sandbox` |

Kill switch: `ENABLED=false` **or** `MODE=off` → zero adapter calls.
Modes `off`/`shadow` never mutate. There is no production/enforce mode.

## Mutation surface (§5)

FILE: CREATE_FILE, WRITE_FILE, REPLACE_FILE, DELETE_FILE, RENAME_FILE
DIR: CREATE_DIRECTORY, DELETE_EMPTY_DIRECTORY
PERM: CHMOD
CONFIG: WRITE_TEST_CONFIG
SERVICE: START/STOP/RESTART/RELOAD_SANDBOX_SERVICE (sandbox daemon only)

Forbidden: package install, firewall, network, users/passwords, SSH,
kernel/sysctl, mounts, production services, production cron, providers.

## Sandbox root

`~/.hermes/sandbox/system-mutation/` — owner=hermes, mode=700.
Subdirs: `.snapshots/`, `.txn/`, `.locks/`, `.service/`.

`resolve_sandbox_path` enforces: lexical normalization, `..` escape,
absolute escape, symlink chains, parent realpath, forbidden prefixes
(/proc /sys /dev /run /etc /boot /root), production ~/.hermes paths.

## Exactly-once (§13)

Durable journal `.txn/transactions.jsonl`: `record_started` writes the
STARTED marker once; duplicate requests replay the prior receipt
(adapter calls = 0). STARTED-without-COMPLETED (crash) is surfaced as
UNKNOWN_OUTCOME and never auto-retried → MANUAL_REVIEW_REQUIRED.

## System Boundary integration (§17)

Every mutation passes SystemBoundaryLayer. NoopSystemBoundary is
forbidden (`BOUNDARY_REQUIRED`). The bridge maps SBL decisions
(BLOCK → DENY with adapter calls = 0). Risk can never decrease after
SBL (P0-14) — the SBL is a restrictive boundary, not a permission
source.

## Sandbox tool registry (§18)

`sandbox_file_create/write/delete/chmod`, `sandbox_service_start/stop/
restart/reload` — registered via `SandboxToolRegistry`, capabilities
`SANDBOX_FILE_MUTATION` / `SANDBOX_SERVICE_CONTROL`, all side-effecting
(never READ_ONLY), no dynamic imports. Production SYSTEM_CONTROL
capability is never used.

## Verification (§19)

Independent checks: exists, content hash, size, mode, owner, realpath,
symlink state. DELETE → target absent + parent intact. CHMOD → exact
permission. Adapter claiming SUCCESS while state differs →
VERIFY_FAILED → rollback.

## CLI (§31)

```
python -m agent.sandbox_runtime.cli status
python -m agent.sandbox_runtime.cli transactions
python -m agent.sandbox_runtime.cli inspect <txid>
python -m agent.sandbox_runtime.cli verify <txid>
```

Read-only by default. Mutation CLI requires explicit `--sandbox
--confirm` (demo only).

## Performance targets (§39)

policy p95 < 1 ms · boundary p95 < 1 ms · sandbox preflight p95 < 5 ms
· transaction orchestration overhead p95 < 10 ms (excluding real
service startup). Measured via `Telemetry.p95`.

## Known limitations

- Sandbox service control is subprocess-based (no systemd units
  created; production units blocked by identity check)
- The `.txn/` journal is JSONL (fsync per append) — durable but not a
  full WAL; sufficient for crash classification
- Fault injection (`FaultInjector`) is available only in
  tests/sandbox (never armed by production code paths)
- Live activation (flags=true + mode=sandbox on the running gateway)
  requires an explicit operator decision + controlled restart
  (Sprint 1.3.5 §40/§42 — NOT performed in this sprint)

## Sprint 1.3.6 recovery hardening

Sprint 1.3.6 сохраняет sandbox-only границу и добавляет durable lifecycle,
read-only recovery scanner/reconciliation, authenticated snapshots,
composite lock identity, durable redacted manual reviews и deterministic
chaos framework. `EXECUTION_STARTED` без подтверждённого
`EXECUTION_COMPLETED` всегда становится `UNKNOWN_OUTCOME`; повтор execute
запрещён. Recovery scanner не вызывает adapter и ничего не исправляет.

Production `SYSTEM_CONTROL` остаётся OFF. Единственная допустимая live
активация — отдельный sandbox subprocess с `ENABLED=true` и
`MODE=sandbox`; gateway restart не требуется.

## Production activation barrier

Sprint 1.3.5/1.3.6 доказывают sandboxed mutation и crash recovery.
Production SYSTEM_CONTROL остаётся OFF. Любая будущая production
активация требует отдельного canary sprint и явного решения оператора.
