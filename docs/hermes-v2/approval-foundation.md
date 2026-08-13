# Approval Foundation — Hermes V2

Sprint 1.0.6.3 · Status: **ACTIVE**

## Model

Durable approvals live in `agent_v2_approvals`:

```
id, run_id, step_id, reason, status,
created_at, expires_at, decided_at,
decision_reason, version, updated_at,
decided_by, decision_source, decision_reason_code
```

The approval is **run-scoped**: every decision requires `run_id` +
`approval_id` + operator identity + `expected_version`. Approving by
`approval_id` alone is rejected when run scope is verifiable.

## States

`PENDING → APPROVED | REJECTED | EXPIRED`

## Security model

| Policy | Behaviour |
|---|---|
| Unauthenticated operator | DENY |
| Authenticated internal operator | may approve **read-only staged approvals only** |
| Write / irreversible actions | DENY regardless of approval |

Operator identity (`OperatorIdentity`) is a minimal foundation:
`operator_id`, `source`, `roles`, `authenticated`. No full IAM in this
sprint; CLI/internal operator only.

## Decision reasons (structured)

`OPERATOR_APPROVED` · `OPERATOR_REJECTED` · `EXPIRED` · `POLICY_DENIED` ·
`RUN_CANCELLED` · `STALE_VERSION`

## Atomicity

Approve is a single transaction:

1. approval `PENDING → APPROVED`
2. step `WAITING_APPROVAL → READY` (approved state)
3. `APPROVAL_APPROVED` event

Guarded by `expected_version` (optimistic concurrency).

## Concurrency & lifecycle guards

| Scenario | Result |
|---|---|
| Double approve (A/B processes) | exactly one wins; second → `ApprovalAlreadyDecidedError` |
| Approve after cancel | DENY — approval cannot resurrect a run |
| Approve after expire | DENY |
| Version mismatch | `StaleVersionError` — reload required, no overwrite |
| Reject | approval → REJECTED; step/run fail per policy; **no tool execution** |

## Resume

After a successful approve of a read-only staged request:
`orchestrator.resume(run_id)` — exactly-once, no duplicate tool, coherent
timeline. After reject, resume is refused (terminal per policy, 0 tool
calls).

## Audit trail

Append-only events: `APPROVAL_VIEWED` (optional), `APPROVAL_APPROVED`,
`APPROVAL_REJECTED`, `APPROVAL_EXPIRED`. Each carries hashed operator id,
decision source, reason code. No secrets, no unnecessary personal data.

## CLI

```bash
python -m agent.operations_v2.cli approvals              # pending list
python -m agent.operations_v2.cli approval <id> --run-id R
python -m agent.operations_v2.cli approve <id> --run-id R --operator ops --confirm [--dry-run] [--note N] [--expected-version V]
python -m agent.operations_v2.cli reject  <id> --run-id R --operator ops --confirm [--dry-run]
python -m agent.operations_v2.cli expire  <id> --run-id R --confirm [--dry-run]
```

Mutation commands **require `--confirm`** (no accidental Enter-to-approve).
`--dry-run` shows run/approval/current state/expected transition/policy
result with **zero writes**.
