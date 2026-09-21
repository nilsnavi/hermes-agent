# Sprint 1.5.6 — Migration Controller Implementation Hardening

## Role
You are the Hermes Migration Controller Contract & Safety Agent.

## Objective
Implement the first isolated, provider/runtime-neutral migration controller contract for Hermes 2.0. This sprint addresses B6 only. The current production runtime remains authoritative. Do not enable migration, shadow traffic, canary traffic, cutover, failover, rollback execution, or production ownership transfer.

## Mandatory repository inspection
Before implementation inspect the exact repository state, including the current migration controller architecture, migration readiness gate, adapter boundary, persistence hardening, and runtime ownership/configuration code. At minimum inspect existing equivalents of:

- `docs/architecture/runtime-migration-controller.md`
- `docs/architecture/migration-readiness-gate.md`
- `docs/architecture/adapter-boundary-design.md`
- `docs/architecture/session-persistence-projection.md`
- `hermes_core/domain/`
- `hermes_core/application/`
- `hermes_core/ports/`
- current runtime selection/startup/configuration paths
- any existing migration/shadow/canary/drain/cutover/rollback/failover/kill-switch code

Do not invent paths. Record exact inspected paths and classify observations as VERIFIED, PARTIAL, or UNVERIFIED.

## Safety boundary
The migration controller is control-plane only. It may decide whether a transition is legal, but it must not route production traffic, execute tools, send deliveries, mutate sessions, call providers, change DNS/proxy, write production DB state, invoke subprocesses, sleep/backoff, or load secrets.

Production migration remains `NO-GO` throughout this sprint.

## Core contracts
Implement immutable provider-neutral values for the following, reusing existing terminology where architecture docs already define it:

### Migration phase
Minimum conceptual phases:
- OFF
- SHADOW
- CANARY
- DRAINING
- CUTOVER
- ROLLBACK

If existing architecture uses different names, preserve those names. Do not invent incompatible production semantics.

### Runtime ownership
Represent authoritative owner separately from candidate owner. SHADOW or CANARY must not imply ownership transfer. Exactly one runtime may be authoritative in any applied state.

### Controller state
Minimum concepts:
- phase
- owner
- candidate_owner
- generation
- kill_switch_enabled
- drain_state
- bounded migration scope

No secrets, SDK clients, HTTP sessions, provider handles, or mutable runtime objects.

### Generation / fencing
State-changing requests must carry `expected_generation`. Successful mutation advances generation exactly once. Stale generation returns explicit conflict; never overwrite, retry silently, or auto-merge.

### Scope
Migration scope must be explicit and bounded. Use only dimensions supported by architecture/runtime evidence. If production mapping is unclear, create the smallest safe generic scope and mark mapping UNVERIFIED. Empty/malformed scope must fail closed.

### Transition request
Immutable transition request with at least:
- transition_id
- expected_generation
- from_phase
- to_phase
- requested_owner
- scope
- stable reason_code

### Transition result
Use explicit immutable statuses such as:
- APPLIED
- NOOP
- REJECTED
- CONFLICT
- KILL_SWITCHED
- INVALID_TRANSITION
- DRAIN_REQUIRED

Equivalent existing names are acceptable. Never use ambiguous `None` for a decision.

### Legal transition graph
Encode one explicit deterministic legal transition graph. Do not allow arbitrary phase jumps. Derive it from architecture evidence. If evidence is incomplete, use conservative fail-closed behavior and document production mapping as UNVERIFIED.

### Kill switch
Kill switch blocks forward migration transitions and ownership transfer to candidate runtime. Enable/disable operations must themselves be generation-fenced. Do not assume rollback bypass behavior unless architecture evidence supports it.

### Drain
Distinguish at least:
- NOT_DRAINING
- DRAIN_REQUESTED
- DRAINED

Do not equate “stop admitting new work” with “all in-flight work complete”. Cutover requiring drain must fail closed before DRAINED.

### Rollback
Rollback must be explicit, generation-fenced, and provider-neutral. The controller may authorize rollback state changes but must not execute runtime rollback or assume external side effects are reversible.

### Failover
Failover must be distinguishable from rollback. If runtime failover semantics are not established, represent them conservatively and mark mapping UNVERIFIED.

### Audit event
Create immutable deterministic audit evidence with at least:
- transition_id
- previous_generation
- new_generation
- status
- reason_code
- from_phase
- to_phase
- previous_owner
- new_owner

No secrets, raw exceptions, provider SDK objects, or runtime clients. Persistence belongs to a future adapter.

### Stable reason codes
Use stable machine-readable codes, e.g. generation_conflict, invalid_transition, kill_switch_enabled, drain_required, scope_invalid, owner_mismatch, already_in_state, rollback_not_allowed, failover_not_allowed. Exact names may differ but must be tested.

## Persistence boundary
If persistence must be represented, model only a future CAS-safe boundary compatible with B1/B2 semantics, e.g. `conditional_save(state, expected_generation)`. Do not implement production DB persistence.

## Required invariants — M1 to M24
Create deterministic isolated tests:

M1 initial controller state has exactly one authoritative owner.
M2 candidate owner is distinguishable from authoritative owner.
M3 same valid input/state produces same decision.
M4 successful state-changing transition increments generation exactly once.
M5 stale expected generation returns explicit CONFLICT.
M6 conflict does not mutate state.
M7 illegal phase jump is rejected.
M8 rejected transition does not advance generation.
M9 no transition can create dual authoritative owners.
M10 SHADOW does not transfer authoritative ownership.
M11 kill switch blocks forward migration.
M12 kill-switch operation is generation-fenced.
M13 malformed/empty scope fails closed.
M14 transition request is immutable.
M15 controller state is immutable.
M16 transition result is immutable.
M17 drain requested is distinguishable from drained.
M18 cutover requiring drain cannot proceed before drained.
M19 rollback is explicit and cannot bypass generation fencing.
M20 failover is distinct from rollback.
M21 NOOP is explicit and does not advance generation.
M22 audit event contains no secret/runtime client/provider SDK object.
M23 all prior isolated Hermes core contracts remain green.
M24 production runtime files remain unchanged.

Add corrective tests for stale kill-switch operations, from-phase mismatch, owner mismatch, malformed reason codes/generation, negative generation, bool-as-generation, wrong-phase cutover, unsupported rollback/failover, stable reasons, and no implicit wall clock. Only implement replay/idempotency semantics if architecture evidence supports them.

## Documentation
Create:
- `docs/architecture/migration-controller-contract.md`
- `docs/architecture/migration-controller-hardening-evidence.md`

Architecture doc must cover purpose, baseline, runtime observations, control-plane boundary, phase, ownership, candidate runtime, state, fencing, scope, transition request/result, transition graph, kill switch, drain, shadow, canary, cutover, rollback, failover, audit, persistence boundary, reason codes, adapter responsibilities, known gaps, migration implications.

Evidence doc must include exact runtime paths inspected, VERIFIED/PARTIAL/UNVERIFIED per area, M1–M24 table with actual tests/results/evidence/limitations, isolation proof, and readiness impact.

End B6 with exactly one of:
- OPEN
- PARTIALLY_ADDRESSED
- READY_FOR_ADAPTER_VALIDATION

Never CLOSED solely from isolated tests. Always state `Production migration: NO-GO`.

## Likely implementation files
Use existing equivalents if already present. Likely candidates:
- `hermes_core/domain/migration.py`
- `hermes_core/application/migration_controller.py`
- `hermes_core/ports/migration.py`
- `tests/hermes_core/test_migration_controller_contract.py`
- the two docs above

Prefer the smallest coherent implementation. Do not create services/ports mechanically if pure domain logic is sufficient.

## Compatibility
Do not break C1–C4 or B1–B5 isolated contracts. The full `tests/hermes_core` suite must remain green.

## No production wiring
Do not add startup integration, live feature flags, request routing integration, real shadow/canary traffic, production migration DB state, provider calls, delivery calls, or tool calls.

## Validation
Run:

```bash
python -m pytest tests/hermes_core --confcutdir=tests/hermes_core -v
python -m compileall hermes_core
python -c "import hermes_core; print('hermes_core OK')"
scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core
git diff --check
git status --short
git diff --stat
git diff --name-only
```

If new files are untracked and absent from `git diff`, use `git add -N <new files>` for audit only, then repeat the diff checks.

Do not commit. Do not push.

## Final report
Return:

```text
Sprint 1.5.6 result:
Files changed:
Tests:
Canonical runner:
Compile/import:
M1-M24:
Production runtime changed: YES/NO
B6:
Production migration:
Known gaps:
```

Expected safety posture:

```text
Production runtime changed: NO
Production migration: NO-GO
```

## Stop conditions
Stop and report instead of guessing if architecture docs contradict each other, production ownership cannot be identified, legal transition graph cannot be derived safely, runtime migration semantics would need to be invented, implementation requires production wiring, CAS/fencing semantics conflict with B1/B2, or isolated testing cannot be preserved.
