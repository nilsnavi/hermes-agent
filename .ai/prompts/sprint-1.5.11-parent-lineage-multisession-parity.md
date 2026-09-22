# Sprint 1.5.11 — Parent Lineage & Multi-Session Isolation Parity

## 1. Mission

Implement one bounded Phase-0 engineering slice that extends the existing offline legacy-vs-core detached session projection parity evidence.

This sprint is limited to exactly two previously UNVERIFIED scenarios:

- SP2 — parent lineage
- SP20 — multiple-session isolation

The goal is to determine, using the real authoritative legacy SessionDB representation and temporary synthetic storage only, whether these two scenarios can be promoted from UNVERIFIED to MATCH.

This sprint MUST NOT broaden into general session migration, runtime integration, shadow execution, lease migration, routing migration, or production ownership transfer.

Starting revision:

`f10c861897ab1f136764e0c6cf80a0d844e505f5`

Treat that revision as the canonical baseline for Sprint 1.5.11.

---

## 2. Baseline

Sprint 1.5.10 established the first bounded paired legacy-vs-core session projection evidence.

Current Sprint 1.5.10 parity totals:

- MATCH: 2
- INTENTIONAL_DELTA: 0
- UNVERIFIED: 18
- NOT_APPLICABLE: 0

Current MATCH observations:

- SP1 — normal active/open
- SP19 — source unchanged / no-write

Current relevant UNVERIFIED observations:

- SP2 — parent lineage
- SP20 — multiple-session isolation

Historical Sprint 1.5.7 parity totals MUST remain separate and unchanged:

- MATCH: 0
- INTENTIONAL_DELTA: 0
- UNVERIFIED: 23
- NOT_APPLICABLE: 1

Do not merge historical Sprint 1.5.7 totals with Sprint 1.5.10 or Sprint 1.5.11 totals.

Current migration readiness remains:

- B1 — PARTIALLY_ADDRESSED
- B2 — PARTIALLY_ADDRESSED
- P — PARTIAL
- B — PARTIAL
- Phase 0 — AUTHORIZED
- Phase 1 — NOT_AUTHORIZED
- Phase 2 — NOT_AUTHORIZED
- Phase 3 — NOT_AUTHORIZED
- Phase 4 — NOT_AUTHORIZED
- Production migration — NO-GO

Sprint 1.5.11 MUST NOT automatically change any of those statuses.

---

## 3. Required Repository Inspection

Before changing code, inspect the actual repository.

At minimum inspect:

- `hermes_state.py`
- `hermes_state_common.py`
- `hermes_state_schema.py`
- `hermes_core/domain/session.py`
- `tests/hermes_core/test_offline_session_projection_parity.py`
- `docs/architecture/offline-session-projection-parity-evidence.md`
- `tests/tui_gateway/test_session_resume_db_ownership.py`
- relevant SessionDB tests
- relevant session creation/read APIs
- actual schema columns related to parent lineage
- actual schema/API behavior for multiple sessions

Do not infer a legacy field or behavior from names alone.

Determine from actual code:

1. How parent-child relationships are represented.
2. Whether `parent_session_id` is persisted directly.
3. Which SessionDB API creates a child session.
4. Which SessionDB API reads parent lineage.
5. Whether `create_session` accepts parent information.
6. Whether another supported legacy method is required.
7. How multiple sessions are keyed.
8. Whether session key uniqueness or lookup semantics affect SP20.
9. Which adapter-owned fields can safely be varied between sessions.
10. Whether any tested operation would touch production state.

Record exact legacy provenance used by the tests.

---

## 4. Hard Safety Boundary

This sprint is Phase 0 only.

MUST NOT:

- access production `HERMES_HOME`;
- open production SessionDB;
- mutate production SessionDB;
- use a real user's session database;
- wire `hermes_core` into gateway/runtime execution;
- enable shadow runtime execution;
- enable Phase 1;
- transfer session ownership;
- change production routing;
- change provider selection;
- invoke providers;
- invoke tools;
- invoke delivery transports;
- make network calls;
- access credentials;
- modify production configuration;
- activate feature flags;
- change migration ownership;
- perform real acquire/release/close session lifecycle effects;
- modify runtime startup behavior merely to make tests pass.

All legacy persistence used by Sprint 1.5.11 MUST live under temporary test-controlled storage such as pytest `tmp_path`.

If satisfying SP2 or SP20 requires production resources, credentials, network access, production HERMES_HOME, or runtime effects: STOP and report the scenario as UNVERIFIED.

---

## 5. Authoritative Legacy Representation

The legacy side MUST use the actual authoritative repository implementation.

Expected source based on Sprint 1.5.10: `hermes_state.SessionDB`.

Verify this again from the current revision.

Do not implement FakeSessionDB, MockSessionDB as legacy provenance, a hand-written replacement SQLite schema, a test-only imitation of SessionDB, or manually constructed rows claimed to be legacy execution.

Mocks may be used only for unrelated out-of-scope effects if absolutely necessary. A mocked or fabricated legacy representation MUST NOT produce MATCH.

---

## 6. Existing Projection Boundary

Reuse the Sprint 1.5.10 detached projection boundary where valid. Do not create a second competing projection model merely for this sprint.

Current expected flow:

`temporary SessionDB fixture → authoritative legacy read → detached projection → normalized comparison → parity classification`

If the existing `project_detached` helper requires a minimal correction to support an actual authoritative legacy field discovered during inspection, the change must remain test-only or isolated, preserve existing behavior, be explicitly justified, not introduce runtime wiring, and not fabricate semantics absent from legacy.

Do not redesign the core session model in this sprint.

---

## 7. SP2 — Parent Lineage Contract

SP2 tests parent-child session lineage. To classify SP2 as MATCH, executable evidence MUST prove all of the following.

### 7.1 Real parent creation

Create a parent session using the actual supported legacy SessionDB API against a temporary database. The parent MUST have a stable, explicitly known identity.

### 7.2 Real child creation

Create a child session using the actual supported legacy API and actual legacy representation for parent lineage. Do not manually inject a parent ID into a fabricated dictionary and call it legacy provenance.

If the supported SessionDB API cannot create or persist parent lineage, inspect whether another authoritative repository API does so. If no safe authoritative representation exists, SP2 remains UNVERIFIED.

### 7.3 Authoritative read

Read the child through the real legacy SessionDB read path. The returned authoritative representation MUST expose the parent relation used for comparison.

### 7.4 Core projection

Project the real legacy child into the detached core representation. Assert normalized equivalence:

`legacy parent identity == projected core parent_session_id`

The comparison must use explicit normalized values rather than object identity.

### 7.5 Parent identity preservation

Prove that the child points to the intended parent, does not point to itself, unrelated sessions do not become the parent, and projection does not alter parent identity.

### 7.6 Detached invariant

Changing detached adapter/test output MUST NOT mutate the legacy source row or source database. The projected core session MUST NOT retain a SessionDB object, SQLite connection, source dictionary alias, or runtime handle.

### 7.7 No-write invariant

The read/projection portion of SP2 MUST be non-mutating. Use an executable no-write check where practical. The existing Sprint 1.5.10 digest/data-version technique may be reused.

Fixture creation is expected to write to the temporary DB. The parity read/projection phase must not write.

---

## 8. SP20 — Multiple-Session Isolation Contract

SP20 tests isolation between multiple real legacy sessions. To classify SP20 as MATCH, executable evidence MUST prove all required properties below.

### 8.1 Multiple authoritative sessions

Create at least two distinct sessions using the real legacy SessionDB API against one temporary test database. Prefer three sessions if that materially improves isolation proof without broadening scope.

Each session MUST have distinguishable values. At minimum distinguish session identity and session key where supported. Where safely supported by actual legacy schema/API, also distinguish one or more adapter-owned values such as source, profile, origin, or other benign metadata. Do not invent unsupported fields.

### 8.2 Independent authoritative reads

Read each session independently through the real legacy API. Assert that lookup for session A does not return session B and vice versa.

### 8.3 Independent projection

Project each authoritative legacy row separately. Assert projected A has A identity, projected B has B identity, keys do not cross, parent lineage does not leak across sessions, and adapter metadata does not alias between projections.

### 8.4 Mutation isolation

Where detached adapter metadata is returned, mutating detached adapter metadata for projected session A MUST NOT mutate legacy source A, legacy source B, or projected adapter metadata B. This is an in-memory detached-object assertion and MUST NOT mutate the database.

### 8.5 Repeated read determinism

Read/project the same session more than once. Equivalent source state MUST produce equivalent normalized projection. Do not require Python object identity; require normalized semantic equivalence.

### 8.6 Cross-session contamination

Explicitly prove that values unique to session A do not appear in session B unless the authoritative legacy representation itself intentionally shares them.

### 8.7 No-write proof

After fixture setup, establish a pre-read database snapshot/digest. Perform legacy reads, detached projections, and isolation assertions. Then establish the post-read database snapshot/digest. The database must remain unchanged for the read/projection phase.

If SQLite/WAL behavior makes raw file digest insufficient, use an appropriate deterministic no-write observation and document its limits.

---

## 9. MATCH Classification Rule

A scenario may become MATCH only when ALL of these are true:

1. Actual authoritative legacy code executed.
2. Legacy provenance is documented.
3. The relevant scenario was actually represented in legacy state.
4. The detached core projection executed.
5. Normalized values were compared.
6. Required equivalence assertions passed.
7. No relevant assertion was skipped.
8. No fake legacy representation supplied the evidence.
9. The scenario-specific contract was actually exercised.

A passing test is not automatically MATCH. A parametrized test that merely executes the same SP1 assertion under a different scenario label is not sufficient. Scenario labels are not evidence.

---

## 10. UNVERIFIED Classification Rule

Keep a scenario UNVERIFIED if authoritative legacy representation cannot safely be produced, a required legacy field is absent, a dependency prevents execution, only core behavior was tested, only a fabricated dictionary was tested, normalized equivalence was not asserted, required no-write/isolation property was not executed, or the scenario was inferred rather than observed.

Explain the exact missing evidence.

---

## 11. NOT_APPLICABLE Classification Rule

Use NOT_APPLICABLE only when repository inspection establishes that the scenario genuinely does not exist in the relevant legacy/core boundary. Do not use NOT_APPLICABLE merely because implementation is inconvenient. Document provenance for any NOT_APPLICABLE decision.

---

## 12. INTENTIONAL_DELTA Classification Rule

Use INTENTIONAL_DELTA only when both legacy and core behavior execute, their difference is real, the difference is deliberate, and the intended difference is documented by an authoritative contract. Do not use INTENTIONAL_DELTA to hide incomplete parity.

---

## 13. Test Placement

Prefer extending `tests/hermes_core/test_offline_session_projection_parity.py`. Do not create a broad new integration framework. A second narrowly scoped test file is acceptable only if there is a clear technical reason.

Keep the harness isolated, deterministic, temporary, deletable, and production-independent.

---

## 14. Required Focused Tests

At minimum provide executable tests for SP2: real parent session fixture, real child session fixture, authoritative child read, parent lineage preservation, detached projection, parent identity normalization, no source aliasing, and no-write read/projection phase.

At minimum provide executable tests for SP20: at least two real sessions, independent reads, independent detached projections, distinct identities, distinct keys where supported, adapter metadata isolation where supported, mutation isolation, repeated projection determinism, cross-session contamination prevention, and no-write read/projection phase.

Do not merely rename generic tests SP2/SP20. Each MATCH classification must map to concrete assertions.

---

## 15. Existing SP1/SP19 Regression

Sprint 1.5.11 MUST preserve Sprint 1.5.10 evidence. SP1 and SP19 must remain green. Do not weaken their assertions.

If SP1 or SP19 regress: STOP. Do not claim Sprint 1.5.11 PASS. Report the regression.

---

## 16. Dependency Boundary

The known safe legacy selector currently has a collection blocker involving `concurrent_log_handler`.

Do not change production behavior merely to bypass this dependency. Before making any dependency change, inspect repository dependency declarations.

If the package is an already-declared supported development/runtime dependency and the current local environment simply lacks it, report that fact. Do not silently install or vendor dependencies from inside the implementation task.

The Sprint 1.5.11 parity harness must not depend on the broad TUI gateway import chain unless actually necessary.

---

## 17. Required Evidence Update

Update `docs/architecture/offline-session-projection-parity-evidence.md` without erasing Sprint 1.5.10 provenance. Add a clearly separated Sprint 1.5.11 section or otherwise make provenance unambiguous.

The evidence MUST contain starting SHA, ending working-tree state, OS, Python version, pytest version, SQLite version, authoritative legacy module/class/API, exact fixture construction, exact read API, exact projection function, exact focused commands, exact test counts, exact full-core counts, canonical runner receipt, compileall receipt, legacy selector receipt, warnings, skips, collection errors, SP2 classification, SP20 classification, Sprint 1.5.11 parity totals, relationship to Sprint 1.5.10, relationship to historical Sprint 1.5.7, B1/B2/P/B reassessment, phase authorization state, and final production migration decision.

---

## 18. Parity Accounting

Keep three evidence generations conceptually separate.

### Historical Sprint 1.5.7

Preserve exactly:

- MATCH 0
- INTENTIONAL_DELTA 0
- UNVERIFIED 23
- NOT_APPLICABLE 1

### Sprint 1.5.10

Preserve its recorded result:

- MATCH 2
- INTENTIONAL_DELTA 0
- UNVERIFIED 18
- NOT_APPLICABLE 0

Do not rewrite Sprint 1.5.10 as if SP2/SP20 had already passed there.

### Sprint 1.5.11

Report the result of this sprint separately. Also report the resulting current SP1-SP20 state after applying valid Sprint 1.5.11 evidence.

If both targeted scenarios become MATCH, the expected current SP1-SP20 state would be MATCH 4, INTENTIONAL_DELTA 0, UNVERIFIED 16, NOT_APPLICABLE 0. This is NOT a required result. Calculate totals from actual evidence.

---

## 19. B1 Reassessment

B1 concerns transactional mutation fencing. SP2/SP20 are primarily read/projection parity evidence. Therefore B1 MUST NOT become CLOSED merely because SP2 or SP20 pass.

Expected conservative result: `PARTIALLY_ADDRESSED`, unless this sprint unexpectedly produces direct evidence relevant to the actual B1 contract without violating scope. Do not broaden scope to obtain such evidence.

---

## 20. B2 Reassessment

B2 concerns persistence projection completeness. SP2 parent lineage and SP20 multi-session isolation directly improve B2 evidence if they execute successfully.

However B2 MUST NOT become CLOSED unless the complete required persistence projection surface is proven. Lease fields, routing affinity, history and other unresolved fields may remain. Classify conservatively.

---

## 21. Gate P Reassessment

Successful SP2/SP20 paired observations improve Gate P evidence. They do not establish global parity. P MUST remain PARTIAL unless all required parity evidence has actually been completed.

This sprint MUST NOT authorize production shadowing merely because four bounded scenarios are MATCH.

---

## 22. Gate B Reassessment

Focused SP2/SP20 evidence alone cannot close B. Account for full hermes_core regression, canonical runner, compileall, known legacy selector collection blocker, remaining UNVERIFIED scenarios, performance evidence, and rollback evidence already established elsewhere. Classify based on actual evidence.

---

## 23. Phase Authorization

Sprint 1.5.11 is Phase 0. Expected authorization state remains:

- Phase 0 — AUTHORIZED
- Phase 1 — NOT_AUTHORIZED
- Phase 2 — NOT_AUTHORIZED
- Phase 3 — NOT_AUTHORIZED
- Phase 4 — NOT_AUTHORIZED

Do not authorize Phase 1 unless every prerequisite from the established migration readiness model is actually satisfied. This sprint alone is not intended to authorize Phase 1.

---

## 24. Production Migration Decision

The default decision remains `NO-GO`. Do not change this merely because SP2/SP20 become MATCH. A GO decision requires the established migration gates, not a local test success.

---

## 25. Required Validation

Run the focused Sprint 1.5.11 tests first using the supported Python environment.

Expected Windows interpreter: `C:\Python314\python.exe`

Focused command:

`C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra`

Then run full core:

`C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra`

Run compileall:

`C:\Python314\python.exe -m compileall hermes_core`

Run canonical Windows validation:

`& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'`

Record exact counts, failures, skips, warnings, durations, discovered files, workers, and completion percentage.

---

## 26. Safe Legacy Selector

Attempt:

`C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra`

If it still fails collection because of `ModuleNotFoundError: concurrent_log_handler`, record COLLECTION ERROR, 0 behavioral tests executed, exact dependency, and exact import chain where practical.

Do not report this as a failed session behavior assertion. Do not silently convert it into PASS. Do not modify production code just to bypass it.

---

## 27. Warning Handling

The known Windows pytest cache warning may occur: `PytestCacheWarning` with `WinError 183`.

Record it accurately. Do not classify it as a behavioral test failure. If a new warning appears, inspect it; do not automatically dismiss new warnings as harmless.

---

## 28. Repository Safety Verification

Before final response run:

- `git diff --check`
- `git diff --stat`
- `git diff --name-only`
- `git status --short`

Confirm that only sprint-scoped files changed. If unrelated files changed: STOP and report them. Do not clean up unrelated user changes automatically.

---

## 29. Stop Conditions

STOP immediately if the work requires production HERMES_HOME, production SessionDB, production credentials, network access, provider calls, tool execution, delivery effects, runtime ownership transfer, gateway wiring, Phase 1 activation, production feature flag changes, schema migration against real state, destructive DB operations, fabricated legacy provenance, or weakening existing SP1/SP19 assertions.

Also STOP if authoritative legacy behavior contradicts assumptions in this prompt. Report actual repository behavior rather than forcing the expected design.

---

## 30. Non-Goals

This sprint does NOT implement production shadow mode, canary migration, cutover, rollback activation, runtime session ownership transfer, lease migration, lease CAS integration, routing migration, provider migration, delivery migration, transcript migration, history migration, performance optimization, gateway integration, production SessionDB migration, production schema migration, or dependency refactoring unrelated to SP2/SP20.

---

## 31. Completion Criteria

Sprint 1.5.11 is complete only when:

1. Repository inspection was performed.
2. Actual parent-lineage representation was identified.
3. Actual multi-session behavior was identified.
4. No fake legacy SessionDB was used.
5. SP2 was executed or honestly left UNVERIFIED.
6. SP20 was executed or honestly left UNVERIFIED.
7. Every MATCH has actual legacy provenance.
8. Existing SP1 remains green.
9. Existing SP19 remains green.
10. Read/projection no-write behavior is preserved.
11. Focused tests were executed.
12. Full hermes_core tests were executed.
13. compileall was executed.
14. Canonical runner was executed.
15. Safe legacy selector was attempted.
16. Warnings/errors/skips were recorded honestly.
17. Evidence document was updated.
18. Sprint 1.5.7 provenance remains unchanged.
19. Sprint 1.5.10 provenance remains separately identifiable.
20. Current SP1-SP20 totals are recalculated from evidence.
21. B1/B2/P/B are reassessed conservatively.
22. Phase authorization is explicitly stated.
23. Production migration decision is explicitly stated.
24. Repository safety checks are clean.
25. No production effect occurred.

---

## 32. Final Response Format

At completion return:

### Sprint result
PASS / PARTIAL / BLOCKED

### Starting revision
Exact SHA.

### Files changed
Exact paths.

### Legacy provenance
Exact module/class/functions used.

### SP2 result
MATCH / INTENTIONAL_DELTA / UNVERIFIED / NOT_APPLICABLE, with concise evidence.

### SP20 result
MATCH / INTENTIONAL_DELTA / UNVERIFIED / NOT_APPLICABLE, with concise evidence.

### Current SP1-SP20 totals
- MATCH
- INTENTIONAL_DELTA
- UNVERIFIED
- NOT_APPLICABLE

### Historical provenance
Confirm Sprint 1.5.7 totals unchanged and Sprint 1.5.10 evidence preserved separately.

### Test receipts
Focused: passed, failed, skipped, warnings, duration.
Full hermes_core: passed, failed, skipped, warnings, duration.
Compileall: PASS/FAIL.
Canonical: files, passed, failed, workers, duration.
Legacy selector: PASS / FAIL / COLLECTION ERROR / UNVERIFIED, exact reason.

### No-write proof
State exactly what was compared and what passed.

### Readiness impact
- B1
- B2
- P
- B

### Phase authorization
- Phase 0
- Phase 1
- Phase 2
- Phase 3
- Phase 4

### Production migration
GO / NO-GO

### Remaining gaps
Only evidence-supported remaining gaps.

### Repository state
Output/summary of `git diff --check`, `git diff --stat`, `git diff --name-only`, and `git status --short`.

Do not commit.
Do not push.
