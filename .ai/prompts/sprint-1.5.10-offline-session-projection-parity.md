# Sprint 1.5.10 — Offline Legacy-vs-Core Detached Session Projection Parity Harness

## Role

You are acting as the senior migration-safety, persistence-boundary, parity, and verification engineer for Hermes 2.0.

This sprint implements exactly one bounded Phase 0 engineering slice:

**offline legacy-vs-core detached session projection parity harness**

The purpose is to obtain real paired legacy/core evidence for session projection without connecting `hermes_core` to the production runtime.

Production migration remains **NO-GO**.

The existing Hermes runtime remains authoritative.

Do NOT enable Phase 1.

Do NOT wire `hermes_core` into gateway/runtime execution.

Do NOT transfer ownership.

---

# 1. Mission

Implement a bounded offline harness that:

1. creates or uses only a temporary synthetic legacy SessionDB fixture;
2. reads the fixture through the real legacy persistence representation where safely possible;
3. projects the selected legacy session representation into a detached `hermes_core.domain.session.Session`;
4. compares explicitly owned fields;
5. preserves adapter-owned metadata separately;
6. proves that the parity operation performs no writes to the source fixture;
7. records actual paired legacy/core observations;
8. distinguishes `MATCH`, `INTENTIONAL_DELTA`, `UNVERIFIED`, and `NOT_APPLICABLE`;
9. produces reproducible evidence for reassessing B1, B2, P, and B;
10. does not modify production runtime behavior.

This sprint must produce evidence, not migration.

---

# 2. Baseline

Start from the current repository state after Sprint 1.5.9.

Expected baseline revision:

`bc16136d5da6cf724dbb9ae172c546d4d0d9162b`

Do not trust historical test counts blindly.

Inspect and re-run the relevant current suites.

Sprint 1.5.9 readiness baseline:

- A = PARTIAL
- C = PASS
- R = UNVERIFIED
- P = PARTIAL
- L = PARTIAL
- S = PARTIAL
- M = UNVERIFIED
- B = PARTIAL

Blockers:

- B1 = PARTIALLY_ADDRESSED
- B2 = PARTIALLY_ADDRESSED
- B3 = CLOSED_AT_CORE_CONTRACT_LEVEL
- B4 = CLOSED_AT_CORE_CONTRACT_LEVEL
- B5 = PARTIALLY_ADDRESSED
- B6 = CLOSED_AT_CORE_CONTRACT_LEVEL
- B7 = PARTIALLY_ADDRESSED

Migration phases:

- Phase 0 = AUTHORIZED
- Phase 1 = NOT_AUTHORIZED
- Phase 2 = NOT_AUTHORIZED
- Phase 3 = NOT_AUTHORIZED
- Phase 4 = NOT_AUTHORIZED

Production migration remains NO-GO.

---

# 3. Required inspection before implementation

Inspect the actual repository before designing the harness.

At minimum inspect:

- `docs/architecture/migration-readiness-reassessment.md`
- `docs/architecture/migration-readiness-gate.md`
- `docs/architecture/session-persistence-projection.md`
- `docs/architecture/session-persistence-hardening.md`
- `docs/architecture/differential-parity-contract.md`
- `docs/architecture/regression-differential-parity-evidence.md`
- `docs/architecture/adapter-boundary-design.md`

Inspect relevant core code:

- `hermes_core/domain/session.py`
- session-related application services
- persistence ports/contracts
- repository abstractions
- candidate/adopt/conditional-save semantics

Inspect relevant legacy persistence/runtime code, including the actual SessionDB implementation and its schema/row representation.

Search rather than assuming exact filenames.

Inspect relevant existing tests:

- `tests/hermes_core/`
- session persistence tests
- differential parity tests
- applicable legacy SessionDB tests
- `tests/tui_gateway/test_session_resume_db_ownership.py`
- any test fixtures/fakes that model the real legacy session row

Document which implementation is the authoritative legacy source for every compared field.

Do not create a parallel invented schema if the repository already defines the real one.

---

# 4. Hard safety boundary

This sprint is Phase 0 only.

Allowed:

- source inspection
- architecture documentation
- isolated tests
- temporary directories
- temporary SQLite databases
- synthetic session records
- test-only/offline adapters
- read-only projection code
- deterministic normalization
- parity observations
- checksums/hashes for no-write proof
- isolated imports of legacy persistence code
- dependency/environment repair required only for isolated test execution, if safe

Forbidden:

- production `HERMES_HOME`
- existing user/session databases
- production SQLite/WAL files
- writes to any real SessionDB
- gateway registration
- runtime wiring
- changing authoritative session ownership
- feature flags affecting runtime
- shadow traffic
- canary traffic
- production traffic
- provider calls
- network calls
- tool execution
- delivery execution
- credentials
- secrets
- migration controller activation
- production schema migration
- destructive migration
- WAL repair on real databases
- background services
- daemon changes

If a test or import would require production resources or effects:

STOP that path and classify the corresponding evidence as `UNVERIFIED`.

---

# 5. Dependency isolation

Sprint 1.5.9 found that:

`tests/tui_gateway/test_session_resume_db_ownership.py`

could not collect because `concurrent_log_handler` was unavailable.

Investigate the supported repository dependency environment.

If the missing dependency is already declared by the project and can be installed/used safely in the isolated development environment, document the supported command/environment required to run the test.

Do not modify production dependency behavior merely to make the test green.

Do not vendor or stub a production dependency unless an existing repository testing convention explicitly supports that approach.

If the legacy import still cannot be executed safely:

record the affected observation as `UNVERIFIED`.

Do not fabricate legacy provenance.

---

# 6. Define the projection boundary

Before implementation, create an explicit field ownership matrix.

For each legacy session field determine one of:

- CORE_OWNED
- ADAPTER_PRESERVED
- LEGACY_ONLY
- DERIVED
- UNVERIFIED
- NOT_APPLICABLE

At minimum inspect and classify, where present:

- session identity
- scope
- owner
- lifecycle/status
- parent session identity
- lease owner
- lease generation/version
- lease expiry
- creation timestamp
- update timestamp
- profile
- source/origin
- transcript/history reference
- routing home/provider affinity
- persistence version/revision
- WAL/DB implementation metadata
- runtime handle/process metadata

Do not force adapter-owned metadata into the core domain model merely to obtain parity.

Do not delete legacy-only fields from the comparison.

Record them explicitly.

---

# 7. Detached projection contract

The harness must project a legacy session representation into a detached core object.

Required invariants:

DPJ1 — source legacy record is not mutated.

DPJ2 — resulting core object does not retain a live SessionDB handle.

DPJ3 — resulting core object does not retain a SQLite connection/cursor.

DPJ4 — resulting core object does not retain a mutable reference to the source row/dict/object.

DPJ5 — projection performs no persistence write.

DPJ6 — projection performs no acquire/release/close session mutation.

DPJ7 — projection performs no provider/tool/delivery/network effect.

DPJ8 — identity is deterministic.

DPJ9 — lifecycle mapping is deterministic.

DPJ10 — parent lineage mapping is deterministic.

DPJ11 — lease mapping is deterministic for fields supported by both representations.

DPJ12 — adapter-owned metadata is preserved outside the core object when required.

DPJ13 — unsupported legacy fields are explicit rather than silently dropped.

DPJ14 — missing legacy fields have explicit behavior.

DPJ15 — malformed or impossible source state fails closed or becomes explicitly `UNVERIFIED`; it must not be silently normalized into a false `MATCH`.

---

# 8. No-write proof

The harness must provide executable evidence that the source fixture remains unchanged.

Use a temporary synthetic database or fixture only.

Capture source state before projection using suitable evidence such as:

- database file hash
- relevant row snapshot
- schema snapshot
- `PRAGMA data_version` where meaningful
- file metadata if reliable
- explicit recording wrapper around mutation methods

Then run projection/parity.

Capture the same evidence afterward.

Prove:

- no row mutation
- no schema mutation
- no unexpected WAL/journal mutation caused by application writes
- no mutation API was invoked by the harness

Be precise about SQLite behavior.

Do not claim that merely opening SQLite can never create auxiliary filesystem artifacts unless the actual connection mode/configuration proves that.

Prefer a genuinely read-only connection when compatible with the real legacy implementation.

If real legacy code cannot operate in read-only mode, keep the database temporary and prove that the projection path itself issued no mutation.

---

# 9. Required parity scenarios

Implement a bounded matrix using synthetic records.

At minimum cover, where representable by the real schema:

SP1 — normal active/open session

SP2 — session with parent lineage

SP3 — session with lease owner

SP4 — session with lease generation/version

SP5 — lease expiry present

SP6 — no lease

SP7 — closed/terminal session

SP8 — expired session if legacy schema represents it

SP9 — profile/source/origin metadata present

SP10 — routing/provider-affinity metadata present

SP11 — transcript/history metadata present

SP12 — unknown or adapter-only metadata preserved

SP13 — missing optional fields

SP14 — missing required identity

SP15 — malformed lifecycle/status

SP16 — malformed lease data

SP17 — repeated projection of the same source is deterministic

SP18 — mutation of detached output cannot mutate source representation

SP19 — source row/database unchanged after projection

SP20 — multiple independent sessions do not leak state across projections

Do not invent legacy capabilities merely to satisfy a scenario.

If the real schema cannot represent a scenario, mark it `NOT_APPLICABLE` or `UNVERIFIED` with reasoning.

---

# 10. Paired parity classification

Every paired observation must use exactly:

- MATCH
- INTENTIONAL_DELTA
- UNVERIFIED
- NOT_APPLICABLE

`MATCH` requires:

1. actual legacy provenance was executed or loaded from the authoritative temporary legacy representation;
2. actual core projection was executed;
3. normalized comparable values are equivalent;
4. provenance is recorded;
5. no unexplained dropped field exists within the comparison scope.

Do NOT classify a core-only assertion as MATCH.

Do NOT classify expected behavior from documentation as MATCH.

Do NOT convert missing legacy execution into MATCH.

`INTENTIONAL_DELTA` requires a documented semantic reason and explicit ownership.

`UNVERIFIED` is correct whenever evidence is insufficient.

---

# 11. Relationship to existing differential parity evidence

Do not rewrite historical Sprint 1.5.7 observations as though they had been executed previously.

Preserve historical provenance.

New Sprint 1.5.10 observations must be clearly identified as new evidence.

If appropriate, map new session-projection observations to the relevant existing DP categories, but preserve:

- historical totals
- new slice totals
- combined interpretation

Never silently replace the original:

- MATCH 0
- INTENTIONAL_DELTA 0
- UNVERIFIED 23
- NOT_APPLICABLE 1

with new totals unless the document explicitly explains which observations have now been superseded by newly executed evidence.

---

# 12. Implementation placement

Prefer the smallest isolated implementation.

Suitable locations may include:

- `tests/hermes_core/`
- a test-support module
- an offline architecture verification helper

Do NOT place the harness in a production runtime import path unless absolutely required by an already-established architecture boundary.

Do NOT register the harness with gateway/runtime startup.

Do NOT introduce a generic abstraction framework for a single bounded projection.

Keep the implementation easy to delete.

---

# 13. Required tests

Add focused tests for the harness.

Tests must prove:

- field ownership classification
- projection determinism
- source immutability
- detached output
- no live DB handle leakage
- no mutable source aliasing
- adapter metadata preservation
- missing-field behavior
- malformed-field behavior
- no-write behavior
- parity classification rules
- provenance requirements for MATCH
- multi-session isolation

Use the real legacy schema/representation wherever safely possible.

Mocks/fakes may be used only for effects that are outside the slice.

Do not mock away the actual legacy representation being evaluated.

---

# 14. Required evidence document

Create:

`docs/architecture/offline-session-projection-parity-evidence.md`

It must contain:

## Executive summary

## Scope and safety boundary

## Repository revision

## Environment

Include:

- OS
- Python
- SQLite
- relevant dependency environment

## Legacy source inspected

Identify the authoritative legacy SessionDB/schema/code path.

## Field ownership matrix

Use a table:

| Field | Legacy representation | Core representation | Owner | Normalization | Evidence |

## Harness architecture

Explain:

legacy temporary fixture
→ read
→ detached projection
→ normalized comparison
→ parity observation

## No-write proof

Record exact evidence.

## Scenario results

Use:

| Scenario | Legacy provenance | Core provenance | Result | Evidence | Notes |

for SP1–SP20.

## Parity totals

Record:

MATCH
INTENTIONAL_DELTA
UNVERIFIED
NOT_APPLICABLE

## Relationship to Sprint 1.5.7 parity evidence

Do not erase historical provenance.

## B1 impact

State precisely whether evidence changes B1.

Do not close B1 merely because reads work.

## B2 impact

State precisely whether the field-preservation gap has been reduced.

## Gate P impact

State whether P remains PARTIAL or changes.

Do not upgrade P based on one bounded session slice unless the original gate definition is actually satisfied.

## Gate B impact

State evidence completeness impact.

## Remaining gaps

## Phase authorization

Phase 1 must remain NOT_AUTHORIZED unless the sprint unexpectedly produces all prerequisites defined by Sprint 1.5.9.

The expected result is that Phase 1 remains NOT_AUTHORIZED.

## Final conclusion

Production migration remains NO-GO.

---

# 15. Optional contract document

Only if the projection semantics cannot be expressed clearly using existing architecture documents, create:

`docs/architecture/offline-session-projection-contract.md`

Do not create this file merely to duplicate existing documentation.

Prefer updating or referencing the existing session projection contract when possible.

---

# 16. Required validation

Run the focused new tests first.

Then run:

`python -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q`

Run:

`python -m compileall hermes_core`

Run the canonical suite on Windows:

`& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'`

Attempt the relevant safe legacy regression selector in the supported dependency environment.

If the environment still prevents collection, report:

`UNVERIFIED`

with the exact dependency/collection error.

Do not hide skips, retries, collection errors, or warnings.

Record:

- executed
- passed
- failed
- skipped
- retried
- collection errors

---

# 17. Repository safety verification

Before and after the harness execution, verify that no production resource was touched.

Inspect relevant environment/configuration without printing secrets.

Confirm that the harness uses only a temporary fixture.

Run:

`git status --short`

`git diff --check`

`git diff --stat`

`git diff --name-only`

Review every changed file.

No unrelated file may be changed.

---

# 18. Stop conditions

STOP implementation and report the affected evidence as `UNVERIFIED` if:

- real production SessionDB access is required;
- credentials are required;
- network access is required;
- provider/tool/delivery effects are required;
- gateway/runtime wiring is required;
- authoritative ownership must change;
- real schema mutation is required;
- a temporary isolated fixture cannot reproduce the relevant legacy representation;
- legacy provenance cannot be executed safely;
- an unexplained semantic divergence appears that requires redesign beyond this slice.

Do not expand scope to solve another subsystem.

---

# 19. Non-goals

Do NOT:

- implement a production SessionDB adapter;
- implement SessionService writes against legacy storage;
- acquire/release/close real sessions;
- migrate transcripts;
- migrate routing ownership;
- migrate provider selection;
- migrate delivery;
- migrate tool execution;
- implement shadow traffic;
- implement canary;
- implement cutover;
- change migration phase authorization;
- solve performance gate M;
- solve all legacy regression gate R;
- close B1 solely from read-only evidence;
- claim global parity from one session slice.

---

# 20. Completion criteria

Sprint 1.5.10 is complete only if:

1. authoritative legacy session representation is identified;
2. a temporary synthetic fixture is used;
3. no production SessionDB is touched;
4. projection is detached;
5. no-write behavior is proven;
6. field ownership matrix exists;
7. adapter-owned fields remain explicit;
8. required applicable SP scenarios execute;
9. unsupported scenarios are honestly classified;
10. MATCH requires real paired provenance;
11. new parity totals are recorded;
12. historical Sprint 1.5.7 provenance is preserved;
13. focused tests pass;
14. full `tests/hermes_core` suite passes;
15. `compileall` passes;
16. canonical runner passes;
17. legacy regression attempt/result is recorded;
18. B1/B2/P/B impacts are explicitly reassessed;
19. Phase 1 is not accidentally authorized;
20. production migration remains NO-GO;
21. no production runtime behavior changes;
22. no unrelated files change.

---

# 21. Final response

Return:

1. files inspected;
2. files changed;
3. authoritative legacy SessionDB implementation identified;
4. field ownership summary;
5. focused test result;
6. canonical core test result;
7. legacy regression result;
8. SP1–SP20 result summary;
9. parity totals;
10. no-write proof;
11. B1 impact;
12. B2 impact;
13. P/B gate impact;
14. phase authorization impact;
15. remaining gaps;
16. final production migration decision.

Do NOT commit.

Do NOT push.
