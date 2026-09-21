# Hermes 2.0 — Sprint 1.5.2 Session & Persistence Contract Hardening

## Role
You are the Hermes Session & Persistence Contract Architecture Agent.

## Mission
Harden the isolated `hermes_core` session and persistence contracts so future runtime adapters can safely implement transactional session mutation, optimistic concurrency control, stale-writer rejection, and complete persistence projection.

This sprint addresses B1 and B2 from the Sprint 1.5.0 Migration Readiness Gate. It does NOT migrate production runtime ownership. The current production runtime remains authoritative.

## Primary Blockers

### B1 — Session mutation is not transactionally fenced
Current risks include stale writers, mutation before persistence succeeds, persistence failure leaving process-local state mutated, lease ownership races, stale release/close, and unsafe future multi-process ownership.

### B2 — Persistence projection is incomplete
Determine from the authoritative runtime which state is domain-owned, adapter-owned, runtime-only, derived, or not yet modelled. Investigate identity/key, profile, source/origin, lifecycle, timestamps/expiry, generation, lease generation/owner, transcript lineage, usage/accounting, compression lineage, routing home, handles/files, and WAL/recovery metadata.

## Non-Goals
This sprint MUST NOT replace production SessionDB, connect `hermes_core` to production, migrate ownership, change production schema/runtime behavior/public APIs, enable migration flags, implement traffic shadowing, remove legacy owners, modify gateway/provider/delivery/capability behavior, implement distributed locking, or declare production migration GO.

## Mandatory First Step — Analyze Existing Infrastructure
Inspect:
- `hermes_core/domain/session.py`
- `hermes_core/application/session_service.py`
- session-related `hermes_core/ports/`
- `tests/hermes_core/test_session_contract.py`
- `docs/architecture/core-contract-test-evidence.md`
- `docs/architecture/migration-readiness-gate.md`
- `docs/architecture/adapter-boundary-design.md`
- `docs/architecture/application-layer-foundation.md`
- authoritative runtime session implementation and SessionDB
- persistence schema and WAL/recovery behavior
- session handles/file ownership
- routing-home/profile/source/origin handling
- compression/transcript/usage state
- existing lifecycle tests
- `AGENTS.md`
- `SECURITY.md`

Do not infer persistence projection from documentation alone. Compare `hermes_core` with actual authoritative runtime representation. Produce a field ownership matrix before implementation.

## Part A — Persistence Projection Analysis
Create `docs/architecture/session-persistence-projection.md`.

Required matrix:
| Runtime field/state | Current owner | Core representation | Persistence requirement | Migration relevance | Status |
|---|---|---|---|---|---|

Classify relevant state as `CORE_OWNED`, `ADAPTER_OWNED`, `RUNTIME_ONLY`, `DERIVED`, or `NOT_YET_MODELLED`.

Do not add fields to `Session` merely because they exist in legacy runtime. Explicitly distinguish DOMAIN STATE, PERSISTENCE METADATA, and RUNTIME RESOURCE OWNERSHIP.

## Part B — Explicit Optimistic Concurrency Contract
Replace ambiguous repository save semantics with an explicit concurrency contract logically equivalent to:

```python
save(session, expected_generation) -> result
```

A stronger atomic command/result abstraction is allowed.

Required semantics:
1. caller supplies expected durable generation;
2. persistence compares it with durable generation;
3. write succeeds only on match;
4. stale writer is rejected;
5. conflict does not overwrite durable state;
6. success and conflict are explicit;
7. persistence/infrastructure failure is distinguishable from conflict.

Prefer explicit immutable result types over ambiguous booleans. Never parse exception text to detect conflicts.

## Part C — Prevent Mutation Before Durable Commit
Avoid:
```text
load -> mutate shared object -> save
```

Guarantee:
```text
load durable state
-> derive isolated candidate
-> conditional persistence
-> commit succeeds
-> return committed state
```

On conflict or persistence failure, original durable/logical state remains authoritative and candidate state is discarded.

Use the simplest sound approach: immutable transition, copy-on-write candidate, atomic repository command, or equivalent. Do not build unnecessary transaction infrastructure.

## Part D — Session Mutation Result Contract
Application-level mutation must distinguish at least:
```text
SUCCESS
CONFLICT
REJECTED
PERSISTENCE_ERROR
```

Exact naming may follow repository conventions. Do not collapse failures into `False`, and do not leak database-specific exceptions through domain/application contracts.

## Part E — Lease Fencing
Preserve the separation between `Session.generation` and `Session.lease_generation`.

Required invariants:
- session generation is persisted state version;
- lease generation is lease ownership epoch;
- stale lease owner/generation cannot mutate newer ownership;
- expected-generation persistence rejects stale session writers.

Required CAS scenario:
```text
durable generation = G
A loads G
B loads G
A derives candidate and conditional-save(expected G) succeeds
durable generation becomes G+1
B conditional-save(expected G) => CONFLICT
B cannot overwrite A
```

Required lease scenario:
```text
A owns lease N
A releases
B acquires lease N+1
stale A attempts release/close/mutation with N
operation fails
B ownership remains unchanged
```

## Part F — Persistence Failure Semantics
Required scenario:
```text
S loaded
candidate derived
repository persistence fails
operation => PERSISTENCE_ERROR
stored S remains unchanged
candidate is not returned as committed
```

Test acquire, release, and close persistence failures. If the current isolated API cannot express safe semantics, deliberately improve the isolated `hermes_core` API and document the change. Do not update production callers.

## Part G — Route/Callback Failure Lease Cleanup Analysis
Inspect the authoritative path:
```text
acquire lease -> route/work -> exception -> who releases?
```

Do not modify production runtime. Document observed ownership/cleanup in `session-persistence-projection.md`. Add isolated tests only if cleanup belongs to the isolated application service. Otherwise record it as unresolved migration work.

## Part H — Repository Contract
The repository port may expose persistence intent such as `create`, `get`, `get_by_key`, and `conditional_save`, following existing architecture.

It MUST NOT expose SQLite connections, cursors, WAL internals, filesystem handles, locks, production SessionDB classes, generic SQL execution, or database-specific transaction APIs into domain/application.

## Part I — Test Harness
Extend tests under `tests/hermes_core/`. Prefer extending `test_session_contract.py`; create `test_session_persistence_contract.py` if clearer.

Use deterministic in-memory fake repositories only. No real DB/SQLite/SessionDB, network, subprocess, sleeps, timing races, or production credentials.

The fake repository must deterministically emulate expected-generation CAS semantics.

## Required Test Scenarios
- P1 successful conditional mutation: load G, transition, save expected G, stored generation G+1.
- P2 stale writer: A/B load G; A commits; B expected G => CONFLICT; A state remains.
- P3 persistence failure: stored state unchanged; candidate not returned as committed.
- P4 lease fencing + persistence fencing.
- P5 stale/concurrent release cannot overwrite current lease state.
- P6 stale/concurrent close cannot overwrite current session state.
- P7 domain rejection is distinguishable from CAS conflict.
- P8 infrastructure failure is distinguishable from CAS conflict.
- P9 projection round-trip preserves every CORE_OWNED field exactly.
- P10 adapter-owned metadata remains outside core ownership and is not silently claimed.

## Object Aliasing Test
Mandatory: prove correctness does not depend on Python object identity. `loaded session`, `candidate session`, and `stored session` must not share mutable identity in a way that lets failed candidate mutation alter stored state.

## Generation Contract
Document precisely:
- when `Session.generation` advances;
- expected generation supplied to persistence;
- generation returned after success;
- behavior on conflict;
- behavior on persistence error;
- behavior on rejected domain transition.

Avoid hidden increments.

## Compatibility
Sprint 1.5.1 C1–C4 are regression evidence. Do not weaken them.

If an intentional contract improvement changes a C1 assertion, document old/new behavior and add stronger replacement coverage. C2/C3/C4 must remain unaffected.

## Evidence
Create `docs/architecture/session-persistence-hardening-evidence.md` with:
1. Scope
2. Baseline (Sprint 1.5.0, B1/B2, Sprint 1.5.1)
3. Persistence Projection
4. Concurrency Contract
5. Mutation Safety
6. Lease Fencing
7. Failure Semantics
8. Test Evidence
9. Isolation Evidence
10. Known Gaps
11. Readiness Impact

For P1–P10 record:
```text
Contract:
Test:
Expected:
Actual:
Result:
Evidence:
Known limitation:
```

Do NOT declare production migration GO.

## Required Validation
Run:
```powershell
python -m pytest tests/hermes_core --confcutdir=tests/hermes_core -v
python -m compileall hermes_core
python -c "import hermes_core; print('hermes_core OK')"
```

Also run the canonical repository runner when available:
```powershell
& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Users/Navitech-home/AppData/Local/Temp/hermes-core-contract-151/Scripts/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'
```

If that temporary environment no longer exists, use a valid isolated environment and record actual path/version. Do not claim full repository regression PASS unless the full authoritative regression suite was actually run.

## Security Constraints
No real API keys, access tokens, provider secrets, passwords, or production credentials in projections/tests/evidence. Credential references remain opaque.

## Architecture Constraints
Maintain dependency direction:
```text
domain
↑
application
↑
ports
↑
future adapters
```

`hermes_core` must not import production runtime implementations or SessionDB. No DB-specific domain logic, runtime globals, hidden singleton repository, or direct filesystem persistence from domain/application.

## Readiness Semantics
At completion classify B1 and B2 as:
```text
OPEN
PARTIALLY_ADDRESSED
READY_FOR_ADAPTER_VALIDATION
```

Do not use CLOSED unless all Sprint 1.5.0 gate evidence actually exists. Production migration remains `NO-GO`.

## Change Discipline
Before editing run:
```powershell
git status --short
```

Expected change areas only:
```text
hermes_core/domain/
hermes_core/application/
hermes_core/ports/
tests/hermes_core/
docs/architecture/session-persistence-projection.md
docs/architecture/session-persistence-hardening-evidence.md
```

Do not modify production runtime directories. Do not commit or push.

## Final Report
Return:
- Files Changed — exact paths.
- Contract Changes — precise API/domain changes.
- Projection Decision — CORE_OWNED / ADAPTER_OWNED / RUNTIME_ONLY boundaries.
- Tests — exact commands/results.
- B1 Status — OPEN / PARTIALLY_ADDRESSED / READY_FOR_ADAPTER_VALIDATION with justification.
- B2 Status — same classification with justification.
- Remaining Blockers — evidence still required before production adapter work.
- Git Diff — `git status --short`, `git diff --stat`, `git diff --name-only`.

Do NOT commit.
Do NOT push.
Stop after Sprint 1.5.2 implementation and evidence generation.
