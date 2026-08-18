# Sandbox Mutation Safety — Sprint 1.3.5

> Hermes Agent 2.0 · safety model of `agent/sandbox_runtime/` · 2026-08-14

## Threat model

The sandbox runtime executes **real state changes** for the first time
in the Hermes 2.0 chain. The threat model assumes an adversary (or a
buggy caller) who can construct arbitrary `SandboxMutationRequest`
objects and try to reach the adapter. The defense is layered:

```
request → model → TTL → replay → path → gateway-guard → SBL
        → plan → preflight → approval → snapshot → lock → TOCTOU
        → adapter → verify → health → commit
```

Every layer can independently DENY. The adapter is reachable only
after ALL gates.

## P0 invariants (§33)

| # | Invariant | Enforcement |
|---|---|---|
| P0-1 | Production mutations = 0 | sandbox root resolution; production paths forbidden |
| P0-2 | Production service restart = 0 | service identity guard |
| P0-3 | Production scheduler mutation = 0 | scheduler not in mutation surface |
| P0-4 | Provider mutation = 0 | providers not in mutation surface |
| P0-5 | Secrets leaked = 0 | security scan + redacted audit |
| P0-6 | Path escape executed = 0 | resolve_sandbox_path DENY |
| P0-7 | Symlink escape executed = 0 | realpath + symlink chain check |
| P0-8 | Adapter after BLOCK = 0 | gates raise before adapter; AdapterAfterBlock sentinel |
| P0-9 | Auto retry after UNKNOWN_OUTCOME = 0 | replay → MANUAL_REVIEW_REQUIRED |
| P0-10 | Duplicate mutation executions = 0 | exactly-once journal |
| P0-11 | Mutation without backup = 0 | snapshot mandatory; BACKUP_FAILED → adapter=0 |
| P0-12 | Commit without verification = 0 | require_verification in store |
| P0-13 | Commit without health = 0 | health gate before COMMITTED |
| P0-14 | Risk decrease after SBL = 0 | SBL is restrictive-only |
| P0-15 | Approval reuse across plans = 0 | plan-scoped approvals |
| P0-16 | Illegal state transitions = 0 | LEGAL_TRANSITIONS map |
| P0-17 | Direct adapter bypass = 0 | pipeline is the only entrypoint |
| P0-18 | Gateway self-restart = 0 | GatewayGuard (direct + indirect) |

## Gateway self-control (§16/§33)

`GatewayGuard` blocks:
- service targets `hermes-gateway` / `hermes-gateway.service`
- payloads matching `systemctl ... restart ... hermes-gateway`
- indirect wrappers: `bash -c`, `sh -c`, `eval(`, `subprocess`,
  `os.system`, `Popen`, script shebangs containing gateway control
- production paths in arguments

Blocked BEFORE the adapter; `adapter_calls` stays 0.

## TOCTOU matrix (§26)

| Test | Scenario | Result |
|---|---|---|
| T1 | file changed after preflight | blocked |
| T2 | inode changed | blocked |
| T3 | symlink swapped | blocked (path escape or TOCTOU) |
| T4 | parent symlink swapped | blocked (path escape or TOCTOU) |
| T5 | permissions changed | blocked |
| T6-T7 | service PID / executable changed | service layer |
| T8 | target deleted | blocked |
| T9 | target created unexpectedly | blocked |
| T10-T12 | approval/plan/boundary drift | approval manager + fingerprints |

All TOCTOU tests assert **adapter calls = 0**.

## Path escape tests (§27)

`../../etc/passwd`, `/etc/passwd`, `sandbox/link -> /etc`, parent
symlink escape, `/proc/self`, `/sys`, `/dev`, `~/.ssh`,
`~/.hermes/config.yaml`, production `state.db`, gateway unit path —
all DENY with zero adapter calls.

## Security scan (§48)

`scan_for_secrets` detects: api keys, passwords, Bearer tokens,
Authorization headers, private keys, AWS/Azure keys, tokens, session
tokens, cookies, secrets. Audit records only operation, resource type,
redacted target, hash, decision, reason, transaction state — never raw
sensitive payloads.

## Failure injection (§23)

Deterministic fault points (tests/sandbox only): FAIL_AFTER_PREFLIGHT,
FAIL_AFTER_BACKUP, FAIL_AFTER_LOCK, FAIL_BEFORE_EXECUTE,
FAIL_DURING_EXECUTE, FAIL_AFTER_EXECUTE, FAIL_BEFORE_VERIFY,
FAIL_DURING_VERIFY, FAIL_AFTER_VERIFY, FAIL_DURING_HEALTH,
FAIL_BEFORE_COMMIT, FAIL_DURING_ROLLBACK, CRASH_AFTER_EXECUTE.
No fault injection in production runtime.

## Kill switch (§42)

`HERMES_SANDBOX_MUTATION_V2_ENABLED=false` or `MODE=off` →
`mutation_allowed=False` → every `run()` returns DENIED before any
side effect. Adapter executions = 0.

## Rollback safety (§22)

- rollback restores file content, existence, permissions, metadata
- rollback passes lock + verification + health
- ROLLED_BACK or ROLLBACK_VERIFY_FAILED → MANUAL_REVIEW_REQUIRED
- rollback never hides the original failure (audit carries both)
- rollback without snapshot → RollbackFailed (fail fast)

## Crash recovery (§24)

TOOL_STARTED without TOOL_COMPLETED → UNKNOWN_OUTCOME → NO automatic
retry → MANUAL_REVIEW_REQUIRED. The transaction scanner
(`recover_transactions`) classifies incomplete transactions on reopen;
never auto-reexecutes.

## Sprint 1.3.6 дополнение

Safety model усилен fail-closed восстановлением: corrupted snapshot,
cross-transaction reuse, ambiguous stale lock, unknown process identity,
partial mutation, rollback failure и timeout никогда не превращаются в
успех. `COMMITTED` валиден только с execution + verification + health
receipts. Manual review хранит минимальные redacted поля без raw payload,
environment, prompt и tool arguments.

## Hard fail conditions (§49)

SPRINT FAIL if any: production mutation > 0, gateway self-restart,
scheduler/provider mutation, unsafe V2 execution, adapter after
DENY/BLOCK, path/symlink escape, TOCTOU bypass, duplicate execution,
approval/backup/verification/health bypass, risk decrease, auto retry
of unknown outcome, secret leak, rollback claims success with
different state, production config change, state corruption.
