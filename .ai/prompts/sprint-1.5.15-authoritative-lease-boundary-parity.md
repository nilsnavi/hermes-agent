# Sprint 1.5.15 — Authoritative Lease Boundary Discovery & Projection Parity

## 1. Mission
Determine the real legacy/runtime authority for session lease state before attempting parity classification, then add only evidence that the repository actually supports.

Target scenarios from the canonical Sprint 1.5.10 matrix:

- SP3 — session with lease owner
- SP4 — session with lease generation/version
- SP5 — lease expiry present
- SP6 — no lease
- SP16 — malformed lease data

Implementation baseline: `630bb3b4316cc95ecfccb406fbf20ce3811579b3`.

Current parity baseline:
- MATCH: 10
- INTENTIONAL_DELTA: 0
- UNVERIFIED: 10
- NOT_APPLICABLE: 0

Current MATCH:
SP1, SP2, SP7, SP9, SP12, SP13, SP17, SP18, SP19, SP20.

Current UNVERIFIED:
SP3, SP4, SP5, SP6, SP8, SP10, SP11, SP14, SP15, SP16.

Phase 0 only. Production migration remains NO-GO.

## 2. Known Architectural Evidence — Verify, Do Not Assume
Existing architecture documentation says:

- core models `lease_owner` and `lease_generation`;
- lease generation is an ownership epoch distinct from session generation;
- runtime authority for lease owner/generation is described as **turn lease tables and gateway state**;
- SessionDB continues to own its own schema/runtime persistence;
- started/updated/expiry state is adapter-owned and not automatically equivalent to a core lease expiry;
- the existing persistence-hardening tests use an in-memory CAS fake and explicitly say real SessionDB adapter integration remains pending.

Treat these statements as inspection leads, not as permission to manufacture parity.

## 3. Critical Rule
Do NOT assume SessionDB session rows are the authoritative lease representation.

Before writing any parity test, locate the actual legacy/runtime lease authority.

Search repository code and tests for concepts including:
- lease
- turn lease
- owner
- generation
- fencing
- acquire/release
- heartbeat
- expiry/TTL/deadline
- stale worker/owner
- gateway ownership
- session registry
- process/run generation

Record exact files, schema/table/state objects and APIs.

## 4. Boundary Decision
Produce an explicit boundary decision before implementation:

### A. SessionDB-row authority
Use this only if the repository proves lease fields are authoritative columns/state in the real SessionDB session representation.

### B. Separate durable lease authority
Use this if lease state is held in another real table/store/API. Tests may use that real temporary authority if it can be instantiated safely without runtime effects.

### C. Gateway/process-only authority
Use this if lease state is runtime memory/process state rather than durable SessionDB projection.

### D. No legacy equivalent
Use this only if repository inspection establishes that a core lease concept has no corresponding legacy concept.

Do not collapse B/C/D into SessionDB metadata.

## 5. Hard Safety Boundary
Allowed:
- source inspection;
- temporary isolated DB/storage;
- real repository-supported lease APIs against temporary storage;
- isolated test fixtures;
- test-only adapters/projection helpers;
- documentation/evidence;
- deterministic clocks only if an existing repository testing seam supports them.

Forbidden:
- production HERMES_HOME;
- real user/session databases;
- real gateway startup;
- network/credentials;
- provider/tool/delivery effects;
- background daemons/watchers;
- production runtime wiring;
- ownership transfer;
- shadow/canary/cutover;
- adding lease columns to SessionDB merely to satisfy SP3–SP6/SP16;
- custom schema presented as legacy authority;
- direct SQL used to manufacture a desired MATCH;
- mapping unrelated fields such as `expiry_finalized`, `ended_at`, `last_activity_at`, message generation or git metadata generation into lease semantics without repository proof.

## 6. SP3 — Lease Owner
Find the authoritative legacy/runtime representation of the current lease owner.

MATCH requires:
1. real authoritative temporary legacy/runtime state;
2. an actual owner value established through supported API/behavior;
3. projection/normalization into the comparable core lease-owner concept;
4. exact semantic equivalence;
5. no production effects.

If no safe authoritative execution exists, remain UNVERIFIED.

## 7. SP4 — Lease Generation/Version
Do not confuse:
- session `generation`;
- core `lease_generation`;
- message/transcript generations;
- git metadata generation;
- migration controller generation;
- process/run generation.

First identify the actual legacy ownership epoch/fencing version.

MATCH requires repository proof that the compared value has lease-generation semantics, not merely that it is an integer named generation.

If semantics differ, use INTENTIONAL_DELTA only when the difference is explicitly documented and evidence-backed. Otherwise UNVERIFIED.

## 8. SP5 — Lease Expiry Present
Do not infer lease expiry from session expiry.

Determine whether the authoritative lease has:
- TTL;
- deadline;
- expires_at;
- heartbeat timeout;
- equivalent ownership-expiration semantics.

`expiry_finalized`, session idle expiry, `ended_at`, or generic timestamps are not lease expiry unless the actual lease implementation proves that relationship.

If no legacy lease-expiry concept exists, NOT_APPLICABLE may be correct only with explicit repository evidence. Otherwise UNVERIFIED.

## 9. SP6 — No Lease
SP6 is not automatically proven by `Session.lease_owner is None` in a newly constructed core object.

MATCH requires authoritative legacy/runtime evidence of the unleased state at the real lease boundary plus the corresponding normalized/core representation.

If the real lease authority can safely create/read an unleased session/turn, use it.

## 10. SP16 — Malformed Lease Data
First establish the real lease representation.

Do not corrupt a database or construct fake legacy lease rows merely to force malformed state.

Helper-only malformed-input tests may prove fail-closed normalization, but do not establish legacy-vs-core MATCH.

If authoritative constraints make malformed lease data impossible at the boundary, document the exact constraints before considering NOT_APPLICABLE. If proof is incomplete, remain UNVERIFIED.

## 11. Relationship to Core Contract
Inspect:
- `hermes_core/domain/session.py`
- `hermes_core/application/session_service.py`
- `hermes_core/ports/persistence.py`
- relevant session persistence tests.

Preserve these semantics:
- lease owner is exclusive;
- acquire increments `lease_generation`;
- release/close require current owner + matching lease generation;
- `generation` is persistence CAS/session-state version;
- `lease_generation` is a distinct ownership epoch;
- candidate mutation is adopted only after persistence success.

Do not modify these semantics in this sprint merely to fit legacy state.

## 12. Required Repository Inspection
At minimum inspect:
- `.ai/prompts/sprint-1.5.10-offline-session-projection-parity.md`
- `docs/architecture/session-persistence-projection.md`
- `docs/architecture/session-persistence-hardening-evidence.md`
- `docs/architecture/offline-session-projection-parity-evidence.md`
- `docs/architecture/runtime-ownership-map.md`
- `docs/architecture/runtime-audit.md`
- `hermes_core/domain/session.py`
- `hermes_core/application/session_service.py`
- `hermes_core/ports/persistence.py`
- relevant `tests/hermes_core`
- actual legacy/runtime files discovered by lease searches.

Search rather than assuming filenames.

## 13. Evidence Strategy
This sprint is discovery-first.

Preferred outcome order:
1. identify authoritative boundary;
2. execute safe real temporary evidence where possible;
3. add parity tests only for scenarios actually supported;
4. leave unsupported scenarios UNVERIFIED/NOT_APPLICABLE honestly;
5. document why.

It is acceptable for this sprint to produce fewer MATCH results than targeted scenarios.

## 14. Existing Parity Must Not Regress
Preserve all existing MATCH classifications:
SP1, SP2, SP7, SP9, SP12, SP13, SP17, SP18, SP19, SP20.

Do not reclassify:
- SP8
- SP10
- SP11
- SP14
- SP15

unless new authoritative evidence unexpectedly and directly establishes them; if that occurs, stop scope expansion and report it rather than changing unrelated classifications.

## 15. Classification Rules
Use exactly:
- MATCH
- INTENTIONAL_DELTA
- UNVERIFIED
- NOT_APPLICABLE

MATCH requires real authoritative legacy/runtime provenance and comparable core/projection execution.

Documentation alone is not MATCH.
Core-only tests are not MATCH.
In-memory core CAS fakes are not legacy parity.
Hand-built lease dictionaries are not authoritative legacy parity.

## 16. Test Placement
If authoritative lease state can be exercised safely, prefer a new focused file when the boundary is not SessionDB row projection, for example:

`tests/hermes_core/test_offline_lease_parity.py`

Do not force lease-boundary tests into `test_offline_session_projection_parity.py` if the authority is separate.

If no authoritative executable boundary can be instantiated safely, documentation-only evidence is acceptable and preferable to fake tests.

## 17. Evidence Document
Append to:

`docs/architecture/offline-session-projection-parity-evidence.md`

with heading:

`## Sprint 1.5.15 — Authoritative Lease Boundary Discovery & Projection Parity`

Record:
- explicit baseline;
- exact searches/files inspected;
- authoritative lease boundary decision;
- lease owner source;
- lease generation source and semantics;
- lease expiry/TTL finding;
- unleased-state representation;
- malformed-state constraints;
- test provenance;
- SP3/SP4/SP5/SP6/SP16 classifications;
- updated totals;
- B1/B2/P/B impact;
- phase authorization;
- production decision.

Do not rewrite historical sections.

## 18. Validation
Run any new focused lease parity test directly.

Then run:

`C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra`

Run:

`C:\Python314\python.exe -m compileall hermes_core`

Run canonical:

`& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'`

Attempt safe legacy selector:

`C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra`

If it remains blocked by `concurrent_log_handler`, record the exact collection result. Do not install/bypass dependencies merely for this selector.

If a different authoritative lease-specific legacy test can be safely run, run the narrowest relevant selector and record it.

## 19. Repository Safety
Before final response run:
- `git diff --check`
- `git diff --stat`
- `git diff --name-only`
- `git status --short`

Review every changed file.

Expected changes:
- evidence document;
- zero or one focused test file;
- possibly an existing test file only if clearly justified.

Production code changes are not expected.

## 20. Readiness Impact
B1 is especially relevant because lease fencing is part of transactional mutation safety.

Do not close B1 from:
- core-only lease tests;
- architecture documentation;
- detached projection alone.

B1 can improve only with authoritative adapter/runtime lease evidence, and closing it requires the original gate requirements, not just this scenario matrix.

B2/P/B remain evidence-driven.

## 21. Phase Authorization
Expected:
- Phase 0 AUTHORIZED
- Phase 1 NOT_AUTHORIZED
- Phase 2 NOT_AUTHORIZED
- Phase 3 NOT_AUTHORIZED
- Phase 4 NOT_AUTHORIZED

No runtime migration authorization is granted by this sprint.

## 22. Production Decision
Production migration remains **NO-GO**.

## 23. Stop Conditions
Stop the affected path and classify conservatively if proof requires:
- production DB/HERMES_HOME;
- live gateway startup;
- real ownership acquisition;
- network/credentials;
- provider/tool/delivery execution;
- background worker/watchers;
- schema mutation;
- direct SQL corruption;
- inventing a legacy lease model;
- modifying core semantics merely to obtain parity.

## 24. Completion Criteria
Sprint 1.5.15 is complete when:
1. authoritative lease boundary is identified or explicitly unresolved;
2. SessionDB row state is not assumed to own lease data without proof;
3. generation concepts are disambiguated;
4. session expiry is not confused with lease expiry;
5. SP3/SP4/SP5/SP6/SP16 are honestly classified;
6. any MATCH has real authoritative provenance;
7. helper/core-only evidence is labeled separately;
8. existing MATCH scenarios remain green;
9. full core and canonical suites pass;
10. safe legacy selector result is recorded;
11. evidence history is preserved;
12. no production runtime behavior changes;
13. Phase 1 remains NOT_AUTHORIZED;
14. production remains NO-GO.

## 25. Final Response
Return:
1. files/searches inspected;
2. authoritative lease boundary decision;
3. exact legacy/runtime lease owner representation;
4. exact lease generation/version representation;
5. exact lease expiry/TTL finding;
6. unleased-state representation;
7. malformed-state constraints;
8. files changed;
9. SP3 result/evidence;
10. SP4 result/evidence;
11. SP5 result/evidence;
12. SP6 result/evidence;
13. SP16 result/evidence;
14. focused/full/compile/canonical/legacy selector results;
15. updated SP1–SP20 totals;
16. B1/B2/P/B;
17. phase authorization;
18. production decision;
19. remaining blockers.

Do not commit.
Do not push.
