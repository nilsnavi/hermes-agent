# Sprint 1.5.14 — Projection Robustness Parity: Optional, Malformed & Deterministic Detached State

## 1. Mission
Extend the Phase 0 offline legacy-vs-core detached session projection parity evidence for:

- SP13 — missing optional fields
- SP14 — missing required identity
- SP15 — malformed lifecycle/status
- SP17 — repeated projection determinism
- SP18 — detached-output mutation cannot mutate source

Do not target SP16 lease data in this sprint. Lease semantics require a separate authoritative slice.

Starting implementation baseline: `50ccd568e5d641d6471ee764e554d4a3460e7f3a`.

Current SP1–SP20 baseline:
- MATCH: 7
- INTENTIONAL_DELTA: 0
- UNVERIFIED: 13
- NOT_APPLICABLE: 0

Current MATCH: SP1, SP2, SP7, SP9, SP12, SP19, SP20.
Current UNVERIFIED: SP3–SP6, SP8, SP10–SP11, SP13–SP18.

Phase 0 is AUTHORIZED for offline/isolated validation only.
Phase 1–4 are NOT_AUTHORIZED.
Production migration remains NO-GO.

## 2. Canonical Scenario Semantics
Use the original Sprint 1.5.10 scenario definitions as authoritative:

- SP13 — missing optional fields
- SP14 — missing required identity
- SP15 — malformed lifecycle/status
- SP16 — malformed lease data
- SP17 — repeated projection of the same source is deterministic
- SP18 — mutation of detached output cannot mutate source representation

This sprint intentionally excludes SP16.

Do not reinterpret these labels to manufacture additional MATCH results.

## 3. Required Inspection Before Implementation
Inspect the current repository at the baseline above, including:

- `tests/hermes_core/test_offline_session_projection_parity.py`
- `docs/architecture/offline-session-projection-parity-evidence.md`
- `.ai/prompts/sprint-1.5.10-offline-session-projection-parity.md`
- `hermes_state_common.py::SCHEMA_SQL`
- authoritative SessionDB create/read paths
- `hermes_state.py::SessionDB._session_row_dict`
- `hermes_core/domain/session.py`
- current test-only `project_detached`

Determine for SP13–SP15:
1. which optional fields can actually be absent/NULL through supported SessionDB behavior;
2. whether required identity can actually be absent in an authoritative SessionDB row;
3. what authoritative malformed lifecycle state can be created safely, if any;
4. whether current schema constraints/APIs prevent malformed/identity-missing rows;
5. which existing tests are helper-contract tests versus authoritative paired provenance.

For SP17/SP18 determine whether existing authoritative tests already execute the exact scenario requirements. Do not count a generic smoke label as proof.

## 4. Hard Safety Boundary
Phase 0 only.

Allowed:
- temporary `tmp_path`
- real temporary `hermes_state.SessionDB`
- supported SessionDB APIs
- read-only SessionDB reads
- test-only projection/helper changes where necessary
- evidence documentation

Forbidden:
- production HERMES_HOME
- real user/session DB
- production DB mutation
- credentials/network
- providers/tools/delivery
- gateway/runtime wiring
- migration flags
- shadow/canary/cutover
- production schema migration
- custom test schema used as authoritative legacy provenance
- direct SQL used merely to manufacture a desired MATCH

## 5. Provenance Rule
MATCH requires actual authoritative legacy provenance plus actual core projection.

A hand-built dictionary may test fail-closed helper behavior, but it MUST NOT by itself establish legacy-vs-core MATCH for SP13, SP14 or SP15.

If the real SessionDB schema/API prevents a malformed or identity-missing state, document that fact. Then classify conservatively according to actual evidence:
- NOT_APPLICABLE only when the scenario truly cannot exist at this projection boundary by authoritative contract;
- otherwise UNVERIFIED.

Do not force MATCH.

## 6. SP13 — Missing Optional Fields
Identify actual optional fields in the SessionDB schema/API.

Prefer a real session created with omitted optional arguments so authoritative `get_session()` returns NULL/default values.

Where authoritative evidence supports it, prove:
- required identity/key remains valid;
- optional NULL/default fields are preserved in the adapter envelope;
- lifecycle normalization remains correct;
- projection succeeds deterministically;
- no source mutation occurs.

Do not treat a required field as optional merely because Python can construct a dict without it.

## 7. SP14 — Missing Required Identity
First determine whether authoritative SessionDB can return a row lacking required identity/key through supported operation.

Do not corrupt the DB via direct SQL solely to manufacture this scenario.

If schema constraints and repository APIs make such a persisted row impossible, document the exact constraints and boundary.

A hand-built malformed dict may still verify `project_detached` fails closed, but that is helper robustness evidence only and cannot be described as paired legacy MATCH.

Required fail-closed behavior for helper-only evidence:
- no fabricated fallback identity;
- no silent normalization to a valid Session;
- deterministic exception/result;
- no source mutation.

## 8. SP15 — Malformed Lifecycle/Status
Sprint 1.5.12 established that authoritative legacy lifecycle uses `ended_at`, not a fabricated `status` column.

Therefore malformed lifecycle evidence must be based on actual `ended_at` semantics.

Inspect whether authoritative SessionDB APIs/schema can create a malformed lifecycle value. If not, do not use direct SQL to force one.

Helper-only malformed input may verify fail-closed behavior (for example an invalid `ended_at` type), but does not by itself prove legacy-vs-core MATCH.

Preserve:
- `ended_at is None` -> ACTIVE
- numeric authoritative `ended_at` -> CLOSED

Do not regress SP7 or SP8 classification.

## 9. SP17 — Repeated Projection Determinism
Use a real authoritative SessionDB row.

Execute projection repeatedly from equivalent authoritative reads and prove:
- equivalent core identity/key/parent/status/metadata;
- equivalent adapter envelope;
- no time/random/environment-dependent projection output;
- no source mutation;
- no hidden shared mutable state.

If already fully proven by an existing authoritative test, it may be promoted only with explicit test-level evidence and a new scenario-specific assertion/receipt if needed.

## 10. SP18 — Detached Mutation Isolation
Use a real authoritative SessionDB row and actual projection.

Prove mutations of:
- core metadata;
- adapter envelope;
- any authoritative mutable projected value if such a value actually exists

cannot mutate:
- original source snapshot;
- fresh authoritative reread;
- another independent projection.

Do not claim nested mutable-object isolation if SessionDB only returns SQLite scalar values/serialized JSON strings. State the scope precisely.

## 11. Existing MATCH Regression
The following must remain green and must not have assertions weakened:

SP1, SP2, SP7, SP9, SP12, SP19, SP20.

SP8 remains UNVERIFIED.
SP3–SP6 lease scenarios remain outside this sprint.
SP10/SP11 remain outside this sprint.
SP16 remains outside this sprint.

## 12. Classification Rules
Use exactly:
- MATCH
- INTENTIONAL_DELTA
- UNVERIFIED
- NOT_APPLICABLE

MATCH requires authoritative paired legacy/core execution.

Helper robustness alone is not MATCH.

NOT_APPLICABLE requires repository evidence that the scenario cannot exist or does not belong to this boundary; use it carefully.

UNVERIFIED is correct when evidence is insufficient.

## 13. Parity Accounting
Starting totals: 7 / 0 / 13 / 0.

Update totals only for SP13, SP14, SP15, SP17, SP18 whose classifications are legitimately changed by this sprint.

Do not assume all five become MATCH.

Preserve historical Sprint 1.5.7 and Sprint 1.5.10–1.5.13 receipts unchanged.

## 14. Evidence Document
Append a new section to:

`docs/architecture/offline-session-projection-parity-evidence.md`

Heading:

`## Sprint 1.5.14 — Projection Robustness Parity`

Record:
- baseline
- inspected schema/APIs
- optional vs required field findings
- lifecycle malformed-state findings
- exact authoritative provenance
- helper-only evidence separately
- SP13/SP14/SP15/SP17/SP18 classification
- exact test names
- validation receipts
- updated current totals
- B1/B2/P/B impact
- phase authorization
- production decision

Do not rewrite earlier sprint sections.

## 15. Test Placement
Prefer extending:

`tests/hermes_core/test_offline_session_projection_parity.py`

Avoid production-code changes. If a production semantic defect appears necessary to fix, stop and report it rather than silently broadening the sprint.

## 16. Required Validation
Run:

`C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra`

Run:

`C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra`

Run:

`C:\Python314\python.exe -m compileall hermes_core`

Run canonical:

`& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'`

Attempt:

`C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra`

If `concurrent_log_handler` still prevents collection, record it as infrastructure/collection blocker, not behavioral failure.

Do not install or bypass dependencies merely for this selector.

## 17. Repository Safety Verification
Run:
- `git diff --check`
- `git diff --stat`
- `git diff --name-only`
- `git status --short`

Expected implementation scope should normally remain:
- `tests/hermes_core/test_offline_session_projection_parity.py`
- `docs/architecture/offline-session-projection-parity-evidence.md`

Review and justify any additional file before completion.

## 18. Readiness Reassessment
B1 must remain PARTIALLY_ADDRESSED unless transactional mutation fencing is independently proven; this sprint is not designed to close it.

B2 may improve from additional projection robustness evidence, but do not close it unless all remaining persistence/projection requirements are actually proven.

P remains evidence-driven and normally PARTIAL while scenarios remain unresolved.

B remains PARTIAL while the legacy selector is blocked and complete regression/performance/rollback/operational evidence is absent.

## 19. Phase Authorization
Expected:
- Phase 0 AUTHORIZED
- Phase 1 NOT_AUTHORIZED
- Phase 2 NOT_AUTHORIZED
- Phase 3 NOT_AUTHORIZED
- Phase 4 NOT_AUTHORIZED

Do not authorize Phase 1 from this slice.

## 20. Production Decision
Production migration remains **NO-GO**.

## 21. Stop Conditions
Stop and report if authoritative proof would require:
- production resources;
- real user DB;
- network/credentials;
- gateway/runtime execution;
- provider/tool/delivery effects;
- production schema changes;
- direct SQL corruption solely to manufacture malformed state;
- production semantic changes outside the bounded projection contract.

## 22. Non-Goals
Do not target:
- SP3–SP6 lease parity
- SP8 expiry runtime
- SP10 routing/provider-affinity
- SP11 transcript/history
- SP16 malformed lease
- migration controller changes
- runtime wiring
- shadow/canary/cutover/failover
- production activation

## 23. Completion Criteria
Complete only when:
1. authoritative optional/required/lifecycle representation is inspected;
2. SP13/SP14/SP15 classifications distinguish authoritative provenance from helper-only robustness;
3. SP17/SP18 use authoritative SessionDB provenance;
4. existing MATCH scenarios remain green;
5. no direct SQL/custom schema is used to manufacture MATCH;
6. focused/full/compile/canonical validation executes;
7. safe legacy selector is attempted and recorded;
8. evidence is appended without rewriting history;
9. repository scope is bounded;
10. Phase 1 remains NOT_AUTHORIZED;
11. production remains NO-GO.

## 24. Final Response Format
Report:
1. inspected schema/APIs;
2. files changed;
3. SP13 classification/evidence;
4. SP14 classification/evidence;
5. SP15 classification/evidence;
6. SP17 classification/evidence;
7. SP18 classification/evidence;
8. helper-only robustness evidence separately;
9. focused/full/compile/canonical/safe-selector results;
10. current SP1–SP20 totals;
11. B1/B2/P/B;
12. phase authorization;
13. production decision;
14. remaining blockers.

Do not commit.
Do not push.
