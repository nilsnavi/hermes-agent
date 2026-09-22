# Sprint 1.5.12 — Lifecycle State Parity: Closed/Terminal & Expired

## 1. Mission
Extend the existing offline legacy-vs-core detached session projection parity harness with narrowly scoped executable evidence for SP7 closed/terminal lifecycle and SP8 expired lifecycle.

Evidence generation only. Do not perform production migration, authorize Phase 1, or wire hermes_core into production gateway/runtime execution.

Starting implementation baseline: `4510c85f913a3a6578e0bdf442bd9f6d6c4c02e4`.

Current parity baseline after Sprint 1.5.11:
- MATCH 4
- INTENTIONAL_DELTA 0
- UNVERIFIED 16
- NOT_APPLICABLE 0

Existing MATCH: SP1, SP2, SP19, SP20.

Phase 0 is AUTHORIZED for offline/isolated validation only. Phase 1–4 are NOT_AUTHORIZED. Production migration is NO-GO.

## 2. Required Repository Inspection
Before changing tests, inspect authoritative repository code and determine:
1. How `hermes_state.SessionDB` represents active sessions.
2. How it represents closed/ended/terminal sessions.
3. Which supported SessionDB API closes/ends a session.
4. Authoritative terminal fields (`ended_at`, `end_reason`, status/state where applicable).
5. Whether a supported API creates/transitions an expired session.
6. Whether expiration is persisted, derived, cleanup behavior, TTL/activity calculation, or absent.
7. How `project_detached` maps lifecycle state into hermes_core.
8. Whether normalization can be proven without production runtime changes.

Record module, class/function, repository path, API, and revision. Do not infer behavior from names/comments when executable implementation can be inspected.

## 3. Hard Safety Boundary
Phase 0 offline evidence only.

MUST NOT:
- open/mutate production `HERMES_HOME`;
- open/mutate real user SessionDB or production database files;
- change gateway/runtime ownership;
- activate migration flags or shadow/canary/cutover;
- invoke providers, tools, or delivery;
- access credentials or network;
- transition a real user session;
- modify production runtime behavior merely to pass tests.

Temporary pytest storage and real `hermes_state.SessionDB` against `tmp_path` are allowed.

## 4. Legacy Provenance Rule
MATCH requires actual authoritative legacy execution.

Acceptable: real `SessionDB`, supported lifecycle APIs, authoritative rows returned by `get_session()` or equivalent, and temporary DBs created by SessionDB.

Do NOT establish MATCH with hand-built legacy dictionaries, mocks/fakes, monkeypatching legacy behavior, replacement schemas, or direct SQL mutation used merely to manufacture state.

If no supported safe API exists, leave the scenario UNVERIFIED. Do not weaken this rule to increase MATCH counts.

## 5. SP7 — Closed / Terminal Lifecycle Contract
If a supported safe API exists, create a temporary session through real SessionDB and transition it through the authoritative lifecycle API.

Prove where supported:
1. real SessionDB creation;
2. authoritative transition;
3. real legacy read exposes terminal state;
4. terminal fields are captured;
5. detached projection maps to expected core lifecycle;
6. identity remains unchanged;
7. parent identity is not corrupted;
8. adapter metadata is detached;
9. projection does not mutate the source row;
10. read/projection does not mutate the temporary DB;
11. repeated projection is deterministic.

MATCH requires actual legacy terminal execution plus normalized equivalence. Core-only evidence remains UNVERIFIED.

## 6. SP8 — Expired Lifecycle Contract
First determine whether expired has an authoritative SessionDB representation. Do not assume expired equals closed.

Determine whether expiration is represented by persisted fields, timestamps, last-activity/TTL derivation, cleanup/selection behavior, another repository mechanism, or no SessionDB representation.

If a supported safe repository path can expose a genuinely expired temporary session, prove:
1. real legacy provenance;
2. authoritative expired semantics;
3. legacy read/selection behavior;
4. detached projection behavior;
5. normalized relation to core state if one exists;
6. no aliasing;
7. no-write during read/projection;
8. deterministic repeated projection.

Do not use direct SQL merely to force timestamps into the past.

If expiration cannot safely be produced through an authoritative path, SP8 remains UNVERIFIED. Consider NOT_APPLICABLE only if repository evidence proves the scenario does not belong to this projection boundary.

## 7. Lifecycle Normalization
Do not invent lifecycle semantics. Use the existing core lifecycle model and projection boundary.

Establish from repository evidence:
- whether legacy ended normalizes to core CLOSED;
- whether `end_reason` is core or adapter metadata;
- whether expired is a core status, adapter condition, or selection rule;
- whether terminal rows remain retrievable through `get_session()`.

Document semantic mismatches; do not silently reinterpret them as MATCH.

## 8. Test Placement
Prefer extending `tests/hermes_core/test_offline_session_projection_parity.py`.

Do not create production runtime modules unless required by an already-existing contract. Preferred implementation is test-only evidence.

## 9. Existing Evidence Regression
SP1, SP2, SP19 and SP20 must remain valid MATCH observations. Do not weaken their assertions. All existing hermes_core tests must remain green.

## 10. Classification Rules
MATCH: actual paired legacy execution plus normalized core equivalence.

UNVERIFIED: authoritative paired evidence was not executed or cannot safely be produced.

INTENTIONAL_DELTA: both sides are authoritative and the difference is deliberate/documented.

NOT_APPLICABLE: repository evidence proves the scenario does not belong to this projection boundary.

Never classify based only on expectation.

## 11. Expected Parity Accounting
Starting totals: MATCH 4, INTENTIONAL_DELTA 0, UNVERIFIED 16, NOT_APPLICABLE 0.

If SP7 and SP8 both legitimately become MATCH: MATCH 6 / UNVERIFIED 14.
If only one becomes MATCH: MATCH 5 / UNVERIFIED 15.
If neither can be executed authoritatively: totals remain unchanged.

Do not force best-case totals.

## 12. Historical Provenance
Do not rewrite historical evidence.

Sprint 1.5.7: MATCH 0 / INTENTIONAL_DELTA 0 / UNVERIFIED 23 / NOT_APPLICABLE 1.
Sprint 1.5.10: MATCH 2 / INTENTIONAL_DELTA 0 / UNVERIFIED 18 / NOT_APPLICABLE 0.
Sprint 1.5.11 baseline: MATCH 4 / INTENTIONAL_DELTA 0 / UNVERIFIED 16 / NOT_APPLICABLE 0.

Append Sprint 1.5.12 as a new evidence generation. Do not modify old receipts with new results.

## 13. Evidence Document
Update `docs/architecture/offline-session-projection-parity-evidence.md` by appending a distinct section:

`## Sprint 1.5.12 — Lifecycle State Parity`

Record inspected APIs, provenance, lifecycle representation, SP7/SP8 results, test names, exact commands/results, focused/full/canonical counts, compileall, safe legacy selector, warnings, current totals, readiness, phase authorization, and migration decision.

Do not rewrite Sprint 1.5.10 or 1.5.11 historical evidence.

## 14. Dependency Boundary
Do not silently install, vendor, or bypass missing dependencies.

Known safe legacy selector blocker: `ModuleNotFoundError: concurrent_log_handler`.

If unchanged, record it as a collection/infrastructure blocker. Do not modify production dependency behavior merely to make the selector collect.

The offline harness may use supported `C:\Python314` if SessionDB imports/executes safely.

## 15. Required Validation
Run:

`C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra`

`C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra`

`C:\Python314\python.exe -m compileall hermes_core`

Run repository canonical tests with `HERMES_PYTHON=/c/Python314/python.exe` against `tests/hermes_core --confcutdir=tests/hermes_core`.

Run:

`C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra`

Record exact outcomes. A collection dependency blocker is not a behavioral failure.

## 16. Repository Safety Verification
Run:
- `git diff --check`
- `git diff --stat`
- `git diff --name-only`
- `git status --short`

Only intended test/evidence files may change during implementation.

## 17. B1 Reassessment
SP7/SP8 parity does not close transactional mutation fencing. B1 remains PARTIALLY_ADDRESSED unless this sprint independently proves all remaining B1 requirements.

## 18. B2 Reassessment
Lifecycle evidence may improve projection coverage, but B2 changes only if executed evidence proves all remaining preservation requirements. Do not close B2 merely because SP7/SP8 pass.

## 19. Gate P Reassessment
P may improve quantitatively but remains PARTIAL while required parity scenarios remain unresolved. Do not authorize migration from counts alone.

## 20. Gate B Reassessment
Focused lifecycle parity cannot establish complete regression, performance, rollback, or operational readiness. Do not close B from this sprint alone.

## 21. Phase Authorization
Expected authorization remains:
- Phase 0 AUTHORIZED
- Phase 1 NOT_AUTHORIZED
- Phase 2 NOT_AUTHORIZED
- Phase 3 NOT_AUTHORIZED
- Phase 4 NOT_AUTHORIZED

This sprint does not authorize production shadowing.

## 22. Production Migration Decision
Production migration remains **NO-GO**. Do not change this merely because SP7 or SP8 becomes MATCH.

## 23. Stop Conditions
Stop and report if validation requires production HERMES_HOME, real user SessionDB, production DB mutation, credentials/network, provider/tool/delivery execution, gateway ownership transfer, production lifecycle transition, unsupported direct SQL as provenance, or production semantic changes solely for testing.

## 24. Non-Goals
Not targeted: lease owner/generation parity; lease expiry unless proven to be authoritative SP8 representation; routing/provider affinity; transcript/history; unknown metadata; migration controller changes; gateway integration; shadow/canary/cutover/failover; production activation.

## 25. Completion Criteria
Complete only when authoritative lifecycle code is inspected; SP7/SP8 have evidence-backed classifications; no MATCH uses synthetic legacy state; SP1/SP2/SP19/SP20 remain green; focused/full/canonical suites execute; compileall passes; safe selector is attempted/recorded; Sprint 1.5.12 evidence is appended without rewriting history; repository scope stays bounded; Phase 1 stays NOT_AUTHORIZED unless separately proven; production remains NO-GO.

## 26. Final Response Format
Report:
1. inspected legacy lifecycle APIs;
2. files changed;
3. SP7 classification/evidence;
4. SP8 classification/evidence;
5. focused result;
6. full-core result;
7. compileall result;
8. canonical result;
9. safe legacy selector result;
10. current SP1-SP20 totals;
11. B1;
12. B2;
13. P;
14. B;
15. phase authorization;
16. production migration decision;
17. remaining blockers.

Do not commit.
Do not push.
