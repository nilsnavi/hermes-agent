# Sprint 1.5.13 — Adapter Metadata Parity: Profile/Source/Origin & Unknown Metadata

## 1. Mission
Extend the offline legacy-vs-core detached session projection parity harness with executable evidence for SP9 (profile/source/origin metadata) and SP12 (unknown/adapter metadata preservation).

Evidence only. Do not perform production migration, authorize Phase 1, or wire hermes_core into production runtime.

Starting implementation baseline: `6b499e3f215d91fe9ad599981a811045cb1aa6e7`.

Current baseline: MATCH 5, INTENTIONAL_DELTA 0, UNVERIFIED 15, NOT_APPLICABLE 0. Existing MATCH: SP1, SP2, SP7, SP19, SP20. SP8 remains UNVERIFIED. Phase 0 AUTHORIZED for offline/isolated validation only; Phase 1–4 NOT_AUTHORIZED; production NO-GO.

## 2. Required Repository Inspection
Before tests, inspect authoritative repository code. Determine which SessionDB fields/APIs own profile/source/origin semantics; whether `profile_name`, `source`, `origin` or equivalents exist; whether routing/provider fields belong elsewhere; which fields are core-owned vs adapter-owned; whether arbitrary/unknown metadata can be produced by supported APIs; and how `project_detached` separates ownership.

Record module, class/function, path, field/API and revision. Do not invent fields absent from the repository.

## 3. Hard Safety Boundary
Phase 0 only. Never access production HERMES_HOME, real user SessionDB, production DB, credentials/network, providers/tools/delivery, gateway ownership, migration flags, shadow/canary/cutover, or production runtime mutation.

Temporary pytest storage and real `hermes_state.SessionDB` against `tmp_path` are allowed.

## 4. Legacy Provenance Rule
MATCH requires actual authoritative legacy execution: real SessionDB, supported APIs, authoritative repository rows and metadata actually persisted/returned by repository code.

Do not establish MATCH with fabricated dictionaries, mocks/fakes, monkeypatched metadata, custom schemas, direct SQL schema changes, or direct SQL inserts/updates used to manufacture metadata.

If repository APIs cannot safely establish a scenario, leave it UNVERIFIED.

## 5. SP9 — Profile / Source / Origin
Inspect schema/APIs first. Where supported, prove real SessionDB creation, real profile/source/origin-related values, authoritative `get_session()` output, correct core normalization, adapter preservation, unchanged identity/key/parent/lifecycle, no aliasing, detached mutation, deterministic repeat projection and no-write.

Do not require an `origin` field if none exists at this boundary. If origin belongs elsewhere, document that precisely. SP9 becomes MATCH only if the actual scenario definition is satisfied by authoritative evidence.

## 6. SP12 — Unknown / Adapter Metadata
Define SP12 at the actual SessionDB projection boundary. Identify repository-produced fields returned by legacy that are not owned by core and must survive in the adapter envelope.

Do not add arbitrary SQL columns or fabricated keys to simulate future metadata.

Where supported, prove real provenance, preservation of multiple adapter-owned fields and types, deep detachment for authoritative mutable values if present, source isolation, deterministic projection, cross-session isolation and no-write.

Do not claim future-schema compatibility unless the repository genuinely provides it. SP12 MATCH may only mean preservation of authoritative adapter-owned metadata returned by the current implementation; state that scope explicitly.

## 7. Core vs Adapter Ownership Table
Evidence must classify inspected fields as core-owned, adapter-owned/preserved, lifecycle-derived, absent at this boundary, or unresolved.

Inspect where present: id, session_key, parent_session_id, source, profile_name, started_at, updated_at, ended_at, end_reason, expiry_finalized, routing/provider-related fields, and other fields returned by authoritative `get_session()`.

## 8. Projection Semantics
Preserve Sprint 1.5.12 lifecycle normalization: `ended_at is None` -> ACTIVE; authoritative ended snapshot -> CLOSED. Do not regress SP7 or reintroduce fabricated legacy `status`.

If metadata work reveals a real lifecycle defect, stop and report instead of silently expanding scope.

## 9. Test Placement
Prefer `tests/hermes_core/test_offline_session_projection_parity.py`. Prefer test-only evidence plus evidence documentation. Do not add production runtime modules unless an existing contract absolutely requires it.

## 10. Existing Evidence Regression
SP1, SP2, SP7, SP19 and SP20 must remain MATCH and their assertions must not be weakened. SP8 remains UNVERIFIED unless independently proven through authoritative expiry execution; this sprint is not permission to reclassify it. All hermes_core tests must remain green.

## 11. Classification Rules
MATCH = actual paired legacy execution plus normalized core/adapter equivalence.
UNVERIFIED = authoritative paired evidence not executed/cannot safely be produced.
INTENTIONAL_DELTA = both sides authoritative and difference deliberate/documented.
NOT_APPLICABLE = repository evidence proves the scenario or precise sub-aspect is outside this boundary.
Never classify from expectation alone.

## 12. Expected Parity Accounting
Starting: MATCH 5 / INTENTIONAL_DELTA 0 / UNVERIFIED 15 / NOT_APPLICABLE 0.

If SP9 and SP12 both legitimately MATCH: 7 / 0 / 13 / 0.
If only one MATCH: 6 / 0 / 14 / 0.
If neither: remain 5 / 0 / 15 / 0.

Do not force best-case totals.

## 13. Historical Provenance
Do not rewrite historical evidence.

Preserve Sprint 1.5.7 = 0/0/23/1; Sprint 1.5.10 = 2/0/18/0; Sprint 1.5.11 current baseline = 4/0/16/0; Sprint 1.5.12 targeted SP7/SP8 = 1 MATCH / 1 UNVERIFIED and current baseline = 5/0/15/0.

Append Sprint 1.5.13 as a new generation only.

## 14. Evidence Document
Update `docs/architecture/offline-session-projection-parity-evidence.md` by appending:

`## Sprint 1.5.13 — Adapter Metadata Parity`

Record inspected schema/APIs, exact provenance, ownership table, SP9/SP12 results, exact test names/commands, focused/full/canonical counts, compileall, safe selector, warnings, current totals, readiness, phase authorization and production decision.

Do not rewrite historical Sprint 1.5.10–1.5.12 evidence.

## 15. Dependency Boundary
Do not install/vendor/bypass missing dependencies. Known safe legacy selector blocker may remain `ModuleNotFoundError: No module named 'concurrent_log_handler'`; record it as collection/infrastructure if still present. Do not change production dependencies to make it collect.

Supported `C:\Python314` may be used for the offline harness.

## 16. Required Validation
Run:

`C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra`

`C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra`

`C:\Python314\python.exe -m compileall hermes_core`

Run canonical repository tests with `HERMES_PYTHON=/c/Python314/python.exe` against `tests/hermes_core --confcutdir=tests/hermes_core`.

Run:

`C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra`

Record exact outcomes. Collection dependency failure is not behavioral failure.

## 17. Repository Safety Verification
Run `git diff --check`, `git diff --stat`, `git diff --name-only`, `git status --short`. Only intended test/evidence files may change.

## 18. B1 Reassessment
SP9/SP12 metadata parity does not close transactional mutation fencing. B1 remains PARTIALLY_ADDRESSED unless independent evidence proves all remaining B1 requirements.

## 19. B2 Reassessment
SP9/SP12 contribute to projection/preservation evidence, but B2 changes only if all remaining requirements are proven. Do not close B2 merely because SP9/SP12 pass.

## 20. Gate P Reassessment
P may improve quantitatively but remains PARTIAL while required parity remains unresolved. Counts alone do not authorize migration.

## 21. Gate B Reassessment
Focused metadata parity cannot establish complete regression, performance, rollback or operational readiness. Do not close B from this sprint.

## 22. Phase Authorization
Expected: Phase 0 AUTHORIZED; Phase 1, 2, 3, 4 NOT_AUTHORIZED. This sprint does not authorize production shadowing.

## 23. Production Migration Decision
Production migration remains **NO-GO** regardless of SP9/SP12 MATCH results.

## 24. Stop Conditions
Stop if work requires production HERMES_HOME, real user DB, production mutation, credentials/network, provider/tool/delivery execution, gateway ownership, production metadata mutation, unsupported direct SQL provenance, custom schema changes to manufacture metadata, or production semantic changes solely for testing.

## 25. Non-Goals
Do not target SP8 runtime expiry, lease parity, routing/provider affinity except boundary ownership inspection for SP9, transcript/history, migration controller, gateway integration, shadow/canary/cutover/failover, or production activation.

## 26. Completion Criteria
Complete only when authoritative metadata implementation is inspected; ownership is documented; SP9/SP12 have evidence-backed classifications; no MATCH uses fabricated metadata; SP1/SP2/SP7/SP19/SP20 remain green; SP8 is not opportunistically reclassified; focused/full/canonical tests execute; compileall passes; safe selector is attempted/recorded; evidence has a separate Sprint 1.5.13 section; history remains intact; scope stays bounded; Phase 1 remains NOT_AUTHORIZED; production remains NO-GO.

## 27. Final Response Format
Report inspected APIs/schema; ownership table; files changed; SP9/SP12 classifications with exact evidence; focused/full/compile/canonical/safe-selector results; current SP1-SP20 totals; B1/B2/P/B; phase authorization; production decision; remaining blockers.

Do not commit.
Do not push.
