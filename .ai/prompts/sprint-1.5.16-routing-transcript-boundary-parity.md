# Sprint 1.5.16 — Routing / Provider Affinity + Transcript / History Authoritative Boundary Parity

## 1. Mission
Continue Phase 0 offline parity work from verified Sprint 1.5.15 baseline `296ed8c6ed664aab85edcea250fbb6796d091df6`.

Target only:
- SP10 — routing / provider-affinity metadata present
- SP11 — transcript / history metadata present

Current baseline: MATCH 12, INTENTIONAL_DELTA 0, UNVERIFIED 8, NOT_APPLICABLE 0.
MATCH: SP1, SP2, SP3, SP6, SP7, SP9, SP12, SP13, SP17, SP18, SP19, SP20.
UNVERIFIED: SP4, SP5, SP8, SP10, SP11, SP14, SP15, SP16.
Phase 0 only. Phase 1–4 NOT_AUTHORIZED. Production migration NO-GO.

## 2. Core Rule
Discovery-first. Do not begin by adding fields to `Session.metadata`. Do not assume routing/provider affinity or transcript/history belong in core `Session`.
First determine authoritative legacy/runtime state, ownership (durable/adapter/derived/process-local), intentional core exclusions, and exact comparable semantics. Only then add parity tests.

## 3. Existing Architectural Constraint
Verify repository evidence rather than assuming it. Known leads: profile/source/chat/thread/origin may be adapter-owned; transcript/messages/FTS/compression may be runtime/adapters; routing-home/index/profile DB path may be adapter-owned; SQLite/WAL resources are runtime concerns.
Do not convert adapter-owned state into core-owned state merely to obtain MATCH.

## 4. Target SP10 — Routing / Provider Affinity
Determine what Sprint 1.5.10 meant by `routing/provider-affinity metadata present`.
Search actual repository concepts: routing, route, provider, affinity, provider selection, model, model_config, profile/profile_name, home, backend, preferred provider, fallback, sticky, model selection, route decision/metadata, session key routing, routing index.
Do not assume similarly named fields have identical semantics.

## 5. SP10 Boundary Decision
Before tests classify authority as one or more:
A. SessionDB durable field.
B. Separate durable routing authority.
C. Adapter-owned state.
D. Runtime-derived state.
E. Process-local state.
F. No current legacy representation (only with repository proof).
Do not collapse distinct concepts into a generic metadata dictionary.

## 6. SP10 Semantic Separation
Distinguish configured provider, selected provider, model, model configuration, profile, routing home, fallback chain, actual provider used for a turn, session affinity, session key, runtime backend/process selection.
Persisted `model` does not prove provider affinity; profile does not prove actual provider selection; fallback config does not prove which provider handled a turn.

## 7. SP10 MATCH Rule
MATCH requires authoritative provenance, supported API/fixture, safe authoritative read, defined comparable projection/adapter representation, preserved semantics, no provider/network execution, and no production state.
If evidence proves only bounded profile/model semantics, do not broaden it to complete routing parity. If SP10 remains broader than evidence, keep UNVERIFIED.

## 8. Target SP11 — Transcript / History
Determine authoritative representation for `transcript/history metadata present`.
Search messages, history, transcript, conversation, generations, conversation_generations, transcript generation, replay, compression/compaction, summaries, FTS, ordering, role/content, tool calls/results, parent/lineage, conversation boundary.

## 9. SP11 Boundary Decision
Classify authority as one or more:
A. SessionDB durable message storage.
B. Separate transcript/message tables.
C. Compression/replay-derived representation.
D. Adapter-owned history.
E. Runtime-only history.
F. No current legacy representation.
Do not assume session row owns transcript state.

## 10. Transcript Semantics
Distinguish session identity, conversation identity, messages, ordering, role/content, transcript generation, conversation generation, compressed history, summary/compaction, FTS/search, delivery state, tool-call/tool-result records.
Message count is not transcript parity. Generation counter is not history contents. FTS is not automatically authoritative message storage. Do not substitute summaries for original history unless repository semantics explicitly permit it.

## 11. SP11 MATCH Rule
MATCH requires real temporary history through supported APIs, read from authoritative storage, preserved identity/order where relevant, detached normalization, deterministic repeated observation/projection, unchanged source, and no network/provider/tool execution.
Hand-built message lists, core-only objects, and fake repositories are not legacy parity.

## 12. Read-Only Observation
Direct SQL SELECT is allowed only when necessary to observe repository-created authoritative state, and only read-only (e.g. SQLite `mode=ro`).
Forbidden: direct SQL INSERT/UPDATE/DELETE, schema fabrication, row corruption, manually fabricated authoritative routing/history rows, replacement schemas.
Prefer supported APIs.

## 13. Isolation
Use temporary isolated storage. Set temporary `HERMES_HOME` before importing modules deriving paths from it.
Do not use production HERMES_HOME/user DBs/live gateway/provider credentials/network/background workers/watch loops/delivery/tool execution/real messaging platforms/production profile mutation.

## 14. Required Repository Inspection
At minimum inspect:
- `.ai/prompts/sprint-1.5.10-offline-session-projection-parity.md`
- this Sprint 1.5.16 prompt
- `docs/architecture/session-persistence-projection.md`
- `docs/architecture/offline-session-projection-parity-evidence.md`
- `docs/architecture/runtime-ownership-map.md`
- `docs/architecture/runtime-audit.md`
- `hermes_state_common.py`
- `hermes_state_sessions.py`
- `hermes_state_messages.py`
- relevant SessionDB mixins
- discovered routing/provider/profile modules
- discovered gateway routing code
- discovered transcript/message/compression code
- existing state/message/history tests
- `hermes_core/domain/session.py`
- `hermes_core/ports`
- existing offline parity tests
Search actual files rather than assuming filenames.

## 15. Preserve Sprint 1.5.15 Lease Findings
Keep SP3 MATCH, SP6 MATCH, SP4 UNVERIFIED, SP5 UNVERIFIED, SP16 UNVERIFIED. Do not reinterpret lease semantics.

## 16. Preserve Existing Parity
Existing MATCH must remain SP1, SP2, SP3, SP6, SP7, SP9, SP12, SP13, SP17, SP18, SP19, SP20.
Do not reclassify SP4, SP5, SP8, SP14, SP15, SP16 in this sprint. Unexpected unrelated evidence should be recorded as a future lead, not scope expansion.

## 17. Classification Rules
Use exactly MATCH, INTENTIONAL_DELTA, UNVERIFIED, NOT_APPLICABLE.
MATCH requires authoritative provenance and comparable semantics.
INTENTIONAL_DELTA requires both sides understood, deliberate difference, explicit architecture permission, and documented evidence.
UNVERIFIED is correct for insufficient evidence.
NOT_APPLICABLE requires proof the scenario genuinely does not exist at the authoritative boundary.

## 18. Test Placement
Prefer `tests/hermes_core/test_offline_routing_parity.py` and/or `tests/hermes_core/test_offline_transcript_parity.py` only where executable authoritative evidence exists.
Documentation-only evidence is preferable to forced tests.

## 19. Evidence Document
Append only to `docs/architecture/offline-session-projection-parity-evidence.md` under:
`## Sprint 1.5.16 — Routing / Provider Affinity + Transcript / History Authoritative Boundary Parity`
Record baseline, searches/files, both boundary decisions and semantic decomposition, executable provenance/classifications, changed files, validation, totals, B1/B2/P/B, phase authorization, production decision, blockers. Do not rewrite historical sections.

## 20. Preferred SP11 Evidence
If repository APIs support it: create temporary session/conversation; append multiple real messages through supported API; read authoritative history; verify identity/order/role/content; create detached normalized representation if needed; repeat deterministically; mutate detached representation; reread source and prove unchanged.
Adapt to actual APIs; do not invent APIs/schema.

## 21. Preferred SP10 Evidence
If safely persisted routing/provider state exists: create temporary session via supported API; set state only through supported API; reread authoritative state; identify exact field semantics; normalize only proven fields; prove detached deterministic representation and unchanged source.
Do not call a real provider. If actual provider selection exists only after live routing, leave that portion UNVERIFIED.

## 22. Production Code
Production code changes are not expected. If parity requires production changes, stop and report missing adapter/contract. Do not modify core domain semantics.

## 23. Validation
Run every new focused test directly.
Then:
`C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra`
`C:\Python314\python.exe -m compileall hermes_core`
Canonical:
`& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'`
Safe legacy selector:
`C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra`
If blocked by `ModuleNotFoundError: concurrent_log_handler`, record as infrastructure/collection blocker, not behavioral failure. Do not install/bypass dependencies merely for collection.
Identify and run narrowest safe existing routing/history legacy selectors discovered.

## 24. Repository Safety
Before final response:
`git diff --check`
`git diff --stat`
`git diff --name-only`
`git status --short`
Review every changed file. Expected scope: evidence document and zero to two focused parity tests. Production code changes are unexpected.

## 25. Expected Outcomes
Do not assume MATCH. Valid outcomes: both MATCH; one MATCH/one UNVERIFIED; or both UNVERIFIED with stronger evidence.
Best-case totals if both MATCH: MATCH 14, INTENTIONAL_DELTA 0, UNVERIFIED 6, NOT_APPLICABLE 0. This is not a quota.

## 26. Readiness
Reassess B1, B2, P, B.
B1 should not improve merely from routing/history evidence.
B2 may improve if persistence projection coverage materially increases, but do not close without original gate requirements.
P/B remain evidence-driven.

## 27. Phase Authorization
Expected: Phase 0 AUTHORIZED; Phase 1–4 NOT_AUTHORIZED. SP10/SP11 parity alone cannot authorize migration phases.

## 28. Production Decision
Production migration remains **NO-GO** unless a separate formally authorized readiness process changes it. Sprint 1.5.16 cannot authorize production migration.

## 29. Stop Conditions
Stop affected path if evidence requires production data/HERMES_HOME, live provider/network/credentials, side-effectful gateway startup, delivery/tool execution, background workers, schema mutation, direct SQL writes, fabricated authoritative rows, core semantic changes, or generic metadata added solely to force parity.
Document blocker and classify conservatively.

## 30. Completion Criteria
Complete when both authoritative boundaries are identified or explicitly unresolved; concepts are semantically separated; MATCH uses real authoritative provenance; no fake repo/direct SQL writes manufacture evidence; temporary state is isolated; prior MATCH remains green; focused/full/compile/canonical validations complete; safe/narrow legacy selector results recorded; evidence remains append-only; no production behavior changes; Phase 1 remains NOT_AUTHORIZED; production remains NO-GO.

## 31. Final Response
Return:
1. actual implementation baseline;
2. searches performed;
3. files inspected;
4. SP10 boundary decision/exact representation/semantic limits/classification/evidence;
5. SP11 boundary decision/exact storage/APIs/semantic limits/classification/evidence;
6. files changed;
7. focused/full/compile/canonical results;
8. narrow legacy routing/history selector results;
9. TUI selector result;
10. updated SP1–SP20 classifications/totals;
11. B1/B2/P/B;
12. phase authorization;
13. production decision;
14. remaining blockers.

Do not commit.
Do not push.
