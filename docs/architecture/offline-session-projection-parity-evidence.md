# Offline session projection parity evidence

Phase 0 only. Production runtime remains authoritative; production migration is **NO-GO**. No production `HERMES_HOME`, SessionDB, gateway wiring, ownership transfer, provider/tool/delivery effect, network, credential or production database was used.

## Historical Sprint 1.5.7 provenance

| Classification | Total |
|---|---:|
| MATCH | 0 |
| INTENTIONAL_DELTA | 0 |
| UNVERIFIED | 23 |
| NOT_APPLICABLE | 1 |

## Historical Sprint 1.5.10 — offline projection baseline

This section is the original Sprint 1.5.10 evidence only. The authoritative source was `hermes_state.SessionDB`, using temporary `tmp_path` storage and a read-only handle. The projection boundary was `project_detached`; adapter-owned metadata stayed outside the core object.

### Validation receipts

- Focused: `C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra` — 24 passed, 0 failed, 0 skipped, 1 `PytestCacheWarning`, 10.35s.
- Full core: `C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra` — 206 passed, 0 failed, 0 skipped, 1 `PytestCacheWarning`, 28.66s.
- Compileall: `C:\Python314\python.exe -m compileall hermes_core` — PASS.
- Canonical: 12 files, 206 tests passed, 0 failed, 100% complete, 19.1s, 24 workers.

### Scenario results

| Scenario | Result | Historical evidence |
|---|---|---|
| SP1 normal active/open | MATCH | Real temporary `SessionDB.get_session("s1")`, detached projection and identity equivalence |
| SP2 parent lineage | UNVERIFIED | No parent-child fixture or lineage assertion in Sprint 1.5.10 |
| SP19 source unchanged/no-write | MATCH | Real temporary SessionDB read/projection with unchanged digest |
| SP20 multiple-session isolation | UNVERIFIED | No multi-session fixture or isolation assertion in Sprint 1.5.10 |

### Sprint 1.5.10 parity totals

| Classification | Total |
|---|---:|
| MATCH | 2 |
| INTENTIONAL_DELTA | 0 |
| UNVERIFIED | 18 |
| NOT_APPLICABLE | 0 |

Sprint 1.5.10 conclusion: SP1 and SP19 were the two MATCH observations. SP2 and SP20 remained unresolved. B1 and B2 remained `PARTIALLY_ADDRESSED`; P and B remained `PARTIAL`. Phase 0 was `AUTHORIZED`; Phase 1–4 were `NOT_AUTHORIZED`; production migration was **NO-GO**.

## Sprint 1.5.11 — parent lineage and multi-session isolation

Canonical baseline: `f10c861897ab1f136764e0c6cf80a0d844e505f5`. The real legacy source remained `hermes_state.SessionDB`; temporary parent/child and three-session fixtures used the actual SessionDB APIs. The detached projection, metadata isolation and digest no-write checks were executed against temporary storage.

### Validation receipts

- Focused: `C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra` — 26 passed, 0 failed, 1 `PytestCacheWarning` (WinError 183), 11.60s.
- Full core: `C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra` — 208 passed, 0 failed, 1 `PytestCacheWarning` (WinError 183), 11.60s.
- Compileall: `C:\Python314\python.exe -m compileall hermes_core` — PASS.
- Canonical: 12 files, 208 tests passed, 0 failed, 100% complete, 36.1s, 24 workers, using `HERMES_PYTHON=/c/Python314/python.exe`.
- Safe legacy selector: `C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra` — COLLECTION ERROR, 0 behavioral tests executed, `ModuleNotFoundError: No module named 'concurrent_log_handler'` through `tui_gateway/server.py → agent/conversation_loop.py → hermes_logging.py`. This is an infrastructure/collection blocker, not a behavioral assertion failure.

### Scenario results

| Scenario | Result | Executed evidence |
|---|---|---|
| SP2 parent lineage | MATCH | `SessionDB.create_session(..., parent_session_id="parent")`, authoritative `get_session()`, legacy child parent ID equals detached core parent ID, non-self lineage, detached metadata and unchanged digest |
| SP20 multiple-session isolation | MATCH | Three real SessionDB sessions, independent reads/projections, distinct identities/keys/profiles, metadata mutation isolation, repeated projection equivalence and unchanged digest |

### Sprint 1.5.11 targeted totals

| Classification | Total |
|---|---:|
| MATCH | 2 |
| INTENTIONAL_DELTA | 0 |
| UNVERIFIED | 0 |
| NOT_APPLICABLE | 0 |

### Current SP1–SP20 totals after Sprint 1.5.11

| Classification | Total |
|---|---:|
| MATCH | 4 |
| INTENTIONAL_DELTA | 0 |
| UNVERIFIED | 16 |
| NOT_APPLICABLE | 0 |

## Readiness impact

- B1 — `PARTIALLY_ADDRESSED`; read/projection parity does not prove transactional mutation fencing.
- B2 — `PARTIALLY_ADDRESSED`; parent lineage and multi-session isolation improve evidence, but complete runtime field preservation remains unproven.
- P — `PARTIAL`; four bounded MATCH observations do not establish global parity.
- B — `PARTIAL`; the safe legacy selector remains blocked and performance/operational evidence is incomplete.

Phase 0 is `AUTHORIZED` for offline/isolated validation only. Phase 1, Phase 2, Phase 3 and Phase 4 are `NOT_AUTHORIZED`. Production migration remains **NO-GO**.

## Sprint 1.5.12 — Lifecycle State Parity

Executed against revision `ab258c7286d48eadeb8a9900280a58bc5c7dc21b`, the explicit user baseline (verified HEAD, initially clean working tree). The canonical prompt is `.ai/prompts/sprint-1.5.12-lifecycle-state-parity.md`; its older starting revision `4510c85f913a3a6578e0bdf442bd9f6d6c4c02e4` was superseded by the user's baseline. No checkout/reset, commit or push was performed. All preceding historical evidence is preserved unchanged.

### Authoritative lifecycle inspection and normalization

The following source was inspected at the baseline above; gateway code was inspected as text, not invoked as a lifecycle fixture.

| Repository source | API / authoritative behavior |
|---|---|
| `hermes_state.py`, `SessionDB` | Real facade used by the tests. `SessionSessionsMixin` supplies session APIs; read-only attachment uses SQLite `mode=ro` without schema initialization. |
| `hermes_state_common.py`, `SCHEMA_SQL` | Session rows have `ended_at REAL`, `end_reason TEXT`, and `expiry_finalized INTEGER DEFAULT 0`; there is no core-style `status` column. |
| `hermes_state_sessions.py`, `SessionSessionsMixin.create_session` / `_insert_session_row` | Creates actual authoritative rows. Initially `ended_at` and `end_reason` are NULL. |
| Same module, `end_session` / `_end_and_bump` | Sets `ended_at=time.time()` and the supplied `end_reason` only while `ended_at IS NULL`; the first end reason wins. Also advances the conversation boundary generation when the update changes a row. |
| Same module, `get_session` | Reads the row by ID, including terminal fields, without filtering out ended sessions. The token flush has an empty-queue fast path in `hermes_state_usage.py`; fixtures enqueue no token updates. |
| Same module, `reopen_session` / `promote_to_session_reset` | Reopening clears terminal fields; promotion persists an explicit reset boundary, including for previously recoverable endings. These paths were inspected, not claimed as executed parity coverage. An ended row is not necessarily permanently unrecoverable. |
| Same module, `set_expiry_finalized` | Persists only a finalization marker. It neither calculates expiry nor sets terminal timestamps/reasons. |
| `gateway/session_lifecycle.py`, `SessionLifecycleMixin._policy_reset_reason` / `_is_session_expired` | Expiry is derived from idle/daily policy, `SessionEntry.updated_at`, current time, platform/session policy, and the active-process guard. It is not equivalent to a non-null `ended_at` or a marker alone. |
| Same module, `set_expiry_finalized`; `gateway/run_watchers.py`, `GatewaySessionWatchersMixin._session_expiry_watcher` / `_finalize_expired_session` | Runtime finalization follows policy selection, invokes finalization/agent cleanup, persists the marker and promotes the reset boundary. This runtime path was not executed within the offline SessionDB-only boundary. |
| `hermes_core/domain/session.py`, `SessionStatus` | Existing states are ACTIVE and CLOSED; there is no EXPIRED enum. |

The test-only `project_detached` now derives ACTIVE/CLOSED from authoritative `ended_at` rather than a fabricated legacy `status` field. SP7 proves normalization of an ended snapshot to CLOSED; it does not prove equivalence of mutation, recovery or reopening contracts. `ended_at`, `end_reason`, `expiry_finalized` and profile data remain explicitly preserved in the deep-copied adapter envelope. Malformed lifecycle validation now checks the actual timestamp field. Production code is unchanged.

### Executed SP7 / SP8 evidence

Both new tests are in `tests/hermes_core/test_offline_session_projection_parity.py`. A file-local autouse fixture sets `HERMES_HOME` under `tmp_path` before lazy legacy imports, because the required `--confcutdir` excludes the repository-wide fixture. Every SessionDB path is explicit temporary test storage. No direct SQL mutation, replacement schema, mocked legacy behavior or manufactured legacy dictionary establishes a MATCH.

| Scenario | Classification | Exact test / assertions and limits |
|---|---|---|
| SP7 closed/terminal | MATCH | `test_sp7_ended_session_projects_closed_without_writes`: real `SessionDB.create_session` creates parent and child; `get_session` proves initial NULL terminal fields and ACTIVE projection; `end_session("child", "session_reset")` produces numeric `ended_at >= started_at` and the exact reason. After writer close, real read-only `get_session` equals the ended row. The detached core is CLOSED; ID/key/parent are preserved, parent is non-self and remains active. Timestamp/reason/profile are retained; repeated projection is equivalent; mutations of adapter and core metadata leave the source and reread unchanged. |
| SP8 expired | UNVERIFIED | `test_sp8_expiry_finalized_flag_does_not_establish_expired_or_closed`: real creation plus `set_expiry_finalized("marked")` produces marker 1 while both terminal fields remain NULL and the core projection remains ACTIVE. Marker preservation, detached mutation, repeated equivalence and unchanged source/digest pass. This is executable evidence against conflating finalization with expiry/closure, not an executed expiry-policy scenario. |

SP8 is not NOT_APPLICABLE: expiry exists in the legacy system and matters to lifecycle, but no SessionDB-only API inspected establishes the complete policy-derived expired condition. Calling `end_session` with an expiry-looking reason or setting the marker would not prove the policy ran. No such shortcut was classified as MATCH. Runtime policy selection/finalization and its equivalent projection remain unverified within this sprint's safe boundary.

No-write proof in both new tests: fixture writes occur only through real SessionDB APIs; the writer is closed before the baseline SHA-256 is captured. Reads/projections use `SessionDB(path, read_only=True)`. The main database digest is identical during read/projection and after reader close; authoritative rereads equal the untouched source after detached metadata mutations. This proves the bounded database-content/read-only projection property, not a claim that SQLite creates no auxiliary lock/sidecar files or that production transactional fencing has been verified.

Existing SP1, SP2, SP19 and SP20 tests remain green with their assertions preserved. The generic twenty-label smoke parametrization is not scenario-specific proof for the remaining UNVERIFIED scenarios.

### Validation receipts

These are executed Sprint 1.5.12 results, not substitutions for prior sprint receipts. The initial sandbox focused attempt reported `No module named pytest` and executed no tests. The same command then ran successfully with approved access to the supported `C:\Python314` environment's installed pytest; no dependencies were installed or bypassed.

| Validation | Exact command | Result |
|---|---|---|
| Focused | `C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra` | 28 passed, 0 failed, 0 skipped; 1 `PytestCacheWarning` (WinError 183); 15.41s; exit 0 |
| Full core | `C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra` | 210 passed, 0 failed, 0 skipped; 1 `PytestCacheWarning` (WinError 183); 15.01s; exit 0 |
| Compile | `C:\Python314\python.exe -m compileall hermes_core` | PASS; exit 0 |
| Canonical | `& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'` | 12 files, 210 passed, 0 failed, 100% complete; 30.7s; 24 workers; exit 0. No skips/retries reported. The initial ~184 estimate is not the executed count. Successful per-file output is summarized, so no independent zero-warning claim is made. |
| Safe legacy selector | `C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra` | COLLECTION ERROR, 0 behavioral tests executed; 1 collection error, 2 `PytestCacheWarning` warnings (WinError 183); 1.40s; exit 1 |

The legacy selector import chain is `tests/tui_gateway/test_session_resume_db_ownership.py → tui_gateway/server.py → agent/conversation_loop.py → hermes_logging.py → concurrent_log_handler`, ending in `ModuleNotFoundError: No module named 'concurrent_log_handler'`. This remains an infrastructure/collection blocker, not a failed behavioral assertion. Cache warnings concern inability to create `.pytest_cache/v/cache` entries; they are not behavioral failures. No warning was silently counted as a failed test or a successful legacy selector.

### Parity accounting after Sprint 1.5.12

| Evidence generation | MATCH | INTENTIONAL_DELTA | UNVERIFIED | NOT_APPLICABLE |
|---|---:|---:|---:|---:|
| Sprint 1.5.12 targeted SP7/SP8 only | 1 | 0 | 1 | 0 |
| Current SP1–SP20 after Sprint 1.5.12 | 5 | 0 | 15 | 0 |

Current MATCH observations are SP1, SP2, SP7, SP19 and SP20. SP3–SP6 and SP8–SP18 remain UNVERIFIED. Historical Sprint 1.5.7, Sprint 1.5.10 and Sprint 1.5.11 totals remain in their original sections; the current count does not rewrite those generations.

### Readiness and authorization after Sprint 1.5.12

- B1 — `PARTIALLY_ADDRESSED`: read-only terminal projection does not close transactional mutation fencing.
- B2 — `PARTIALLY_ADDRESSED`: one additional lifecycle snapshot is preserved, while expiry and other required preservation scenarios remain unresolved.
- P — `PARTIAL`: 5 MATCH / 15 UNVERIFIED does not establish complete parity.
- B — `PARTIAL`: the legacy collection blocker and incomplete regression/performance/rollback/operational evidence remain.

Phase 0 remains `AUTHORIZED` for offline/isolated validation only. Phase 1, Phase 2, Phase 3 and Phase 4 remain `NOT_AUTHORIZED`. No production home/database, network, credentials, provider/tool/delivery execution, runtime wiring, ownership transfer or shadow/canary/cutover was used. Production migration remains **NO-GO**.

## Sprint 1.5.13 — Adapter Metadata Parity

Baseline: `4502bc8f9564479ef6eb16a6ab38d0b38a819af7` (verified HEAD, clean initial working tree). The user's explicit baseline supersedes `6b499e3f215d91fe9ad599981a811045cb1aa6e7` in `.ai/prompts/sprint-1.5.13-adapter-metadata-parity.md`. This section is a new evidence generation; Sprint 1.5.10–1.5.12 sections and historical receipts are unchanged.

### Inspected schema, APIs and ownership

Inspected at the baseline above: `hermes_state_common.py::SCHEMA_SQL`; `hermes_state_sessions.py::SessionSessionsMixin._insert_session_row`, `create_session`, `_inherit_parent_session_metadata`, `get_session` and model-config mutation helpers; `hermes_state.py::SessionDB._session_row_dict`; `hermes_core/domain/session.py::Session`; and the test-only `project_detached`. `gateway/session_recovery.py::_origin_json` and its creation call site were read as source only: gateway serializes source metadata into the real `origin_json` column. No gateway lifecycle or routing path was executed for this evidence.

`create_session` accepts explicit profile/source/origin-related inputs and inserts them into the real schema. `model_config` is serialized with `json.dumps`. `get_session` selects the authoritative row and resolves system-prompt text; `_session_row_dict` does not decode JSON into nested mutable values. The tests therefore compare actual SQLite scalar values, including serialized JSON strings. They do not feed constructed legacy rows into the projection.

Ownership below describes this detached projection boundary, not transfer of production authority:

| Inspected fields | Ownership / treatment |
|---|---|
| `id`, `session_key`, `parent_session_id` | Core identity/key/lineage; projected into existing domain value objects. |
| `source` | Stored by legacy; explicitly represented in core `metadata["source"]` by the existing helper. Not duplicated into the adapter envelope. |
| `profile_name` | Adapter-owned/preserved; explicit fixture profile avoids home-derived profile discovery. No profile-based authorization claim. |
| `origin_json`, `user_id`, `chat_id`, `chat_type`, `thread_id`, `display_name` | Adapter-owned/preserved origin/routing context. `origin_json` exists as TEXT and is accepted by `create_session`; a literal `origin` field is absent at this boundary. No routing behavior is exercised. |
| `started_at`, `last_activity_at` | Adapter-owned/preserved timestamps. No top-level `updated_at` column exists in the inspected session schema; it is not invented or substituted for another timestamp. |
| `ended_at` | Lifecycle-derived: NULL -> ACTIVE, non-NULL authoritative ended snapshot -> CLOSED; raw value also preserved in adapter metadata. Sprint 1.5.12 mapping is unchanged. |
| `end_reason`, `expiry_finalized` | Adapter-owned/preserved. Neither is reinterpreted as an expired core status; SP8 stays UNVERIFIED. |
| `model`, `model_config`, `billing_provider`, `billing_base_url`, `billing_mode` | Adapter-owned/preserved values at this boundary; no provider execution or affinity equivalence claim. JSON config remains text. |
| `cwd`, `git_repo_root`, `git_branch`, `git_metadata_generation`, `system_prompt`, `system_prompt_hash` | Adapter-owned/preserved; no filesystem/project activation or prompt execution. |
| Counters, costs/pricing fields, title/activity/handoff/compression fields, `archived`, `pinned`, `hidden`, `last_read_at`, `tool_names` | Remaining current-schema fields are preserved in the adapter envelope with their returned values/types, including NULL/default values. Passing preservation does not prove the behavior of these subsystems. |
| Core `generation`, `lease_generation`, `lease_owner` | Existing core defaults; not derived from legacy metadata. Mutation/lease parity is unresolved. |
| Arbitrary new top-level metadata keys / future columns | No generic top-level metadata creation API was established. Future-schema compatibility is not claimed. Existing JSON fields accept serialized content, but tests use existing fields and known payload keys only. |

### Executed evidence and classifications

Both tests use the existing `isolated_legacy_home` fixture, real `hermes_state.SessionDB`, explicit `tmp_path` database paths and supported `create_session` calls. Production runtime and `project_detached` were not modified. No direct SQL, custom schema, fabricated returned keys or monkeypatched legacy values are used by these tests.

| Scenario | Result | Exact executable evidence |
|---|---|---|
| SP9 profile/source/origin | MATCH | `test_sp9_real_profile_source_origin_preserved`: creates real parent/child rows with explicit `source="local"`, `profile_name="offline"`, `origin_json`, chat/user/display fields. Authoritative reread equals the supplied profile/source/origin values; core source, ID/key/parent and ACTIVE lifecycle match the row; adapter fields retain values/types. Profile/origin stay outside core metadata. Repeated projection is equivalent; replacing core source and adapter profile/origin does not change the source or durable reread. |
| SP12 unknown/adapter metadata | MATCH, current-schema scope only | `test_sp12_real_adapter_fields_preserve_types_and_session_isolation`: creates two real sessions with distinct models, serialized model configs, profiles, display names and cwd strings. Checks persisted fixture values, JSON content, float timestamp/int marker/string config/NULL reason, and exact preservation of every returned non-core field and its type. Core identity/key/lifecycle remain correct. Mutating one projection's config/display/source leaves the other projection, both original rows and fresh projections unchanged. |

SP12 means preservation of authoritative fields outside core ownership in the current repository, not arbitrary future fields. Returned row values in this fixture are scalars; `origin_json` and `model_config` are immutable strings. No authoritative nested mutable value is returned here, so nested-object detachment is not claimed. The separate adapter dictionary and core metadata dictionary are mutation-tested. The older hand-built `unknown` helper test is not provenance for this MATCH.

No-write proof: writer creation/setup is completed and writer closed before baseline SHA-256. Real readers use `SessionDB(path, read_only=True)`. Main database digests remain identical during projection and after reader close. Source snapshots equal fresh authoritative reads after detached mutations. This is bounded read/projection content evidence, not absence of SQLite sidecar activity or a production fencing guarantee.

### Validation receipts

| Check | Exact command | Executed result |
|---|---|---|
| Focused | `C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra` | 30 passed, 0 failed, 0 skipped; 1 `PytestCacheWarning` (WinError 183); 16.84s; exit 0 |
| Full core | `C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra` | 212 passed, 0 failed, 0 skipped; 1 `PytestCacheWarning` (WinError 183); 17.28s; exit 0 |
| Compileall | `C:\Python314\python.exe -m compileall hermes_core` | PASS; exit 0 |
| Canonical | `& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'` | 12 files, 212 passed, 0 failed, 100% complete; 32.0s; 24 workers; exit 0. No skips/retries reported; summarized successful-file output does not establish zero warnings. The initial ~186 estimate is not the executed count. |
| Safe legacy selector | `C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra` | COLLECTION ERROR; 0 behavioral tests executed; 1 collection error, 2 `PytestCacheWarning` warnings (WinError 183); 1.36s; exit 1 |

The supported Python environment was used with approved access to installed pytest; no dependencies were installed or bypassed. Safe-selector import chain: `tests/tui_gateway/test_session_resume_db_ownership.py → tui_gateway/server.py → agent/conversation_loop.py → hermes_logging.py → concurrent_log_handler`; error: `ModuleNotFoundError: No module named 'concurrent_log_handler'`. This is an infrastructure/collection blocker, not a behavioral failure. Cache warnings concern `.pytest_cache/v/cache` creation and are not behavioral failures either.

### Parity, readiness and authorization

| Generation | MATCH | INTENTIONAL_DELTA | UNVERIFIED | NOT_APPLICABLE |
|---|---:|---:|---:|---:|
| Sprint 1.5.13 targeted SP9/SP12 | 2 | 0 | 0 | 0 |
| Current SP1–SP20 after Sprint 1.5.13 | 7 | 0 | 13 | 0 |

Current MATCH: SP1, SP2, SP7, SP9, SP12, SP19, SP20. SP3–SP6, SP8, SP10–SP11 and SP13–SP18 remain UNVERIFIED. Previous MATCH assertions were not weakened and pass. Historical generations retain their original totals; SP8 was not reclassified.

- B1 — `PARTIALLY_ADDRESSED`: metadata preservation does not prove transactional mutation fencing.
- B2 — `PARTIALLY_ADDRESSED`: current metadata coverage improves, but remaining preservation requirements are unresolved.
- P — `PARTIAL`: 13 scenarios remain UNVERIFIED; counts do not authorize migration.
- B — `PARTIAL`: legacy collection remains blocked; complete regression, performance, rollback and operational evidence is absent.

Phase 0 is `AUTHORIZED` for offline/isolated validation only. Phase 1–4 are `NOT_AUTHORIZED`. Production migration remains **NO-GO**. No production HERMES_HOME/user DB, credentials/network, provider/tool/delivery execution, runtime wiring, ownership transfer or shadow/canary/cutover was used. No commit or push was performed.

## Sprint 1.5.14 — Projection Robustness Parity

Explicit baseline and verified starting HEAD: `e76490db3887f17a29f5abe8f7fc1fbb67cc891c`; initial working tree was clean. The older `50ccd568e5d641d6471ee764e554d4a3460e7f3a` in `.ai/prompts/sprint-1.5.14-projection-robustness-parity.md` was not checked out. No checkout/reset, commit or push was performed. This appended generation preserves all previous evidence, including Sprint 1.5.10–1.5.13.

### Inspection: optional, required and lifecycle fields

Inspected before implementation: the existing test/evidence files, original SP13–SP18 definitions in `.ai/prompts/sprint-1.5.10-offline-session-projection-parity.md`, `hermes_state_common.py::SCHEMA_SQL`, `hermes_state_sessions.py::SessionSessionsMixin._insert_session_row`, `create_session`, `get_session`, `end_session`, `reopen_session`, `hermes_state.py::SessionDB._session_row_dict`, and `hermes_core/domain/session.py::Session`. Findings apply to the explicit baseline above.

- Optional arguments such as model/config/prompt, user/chat/thread/origin/display, cwd/git and parent may be omitted. Real rows retain the schema keys with NULL values; omission of a Python dictionary key is not the authoritative representation. Counters/flags have real defaults. SP13 supplies an explicit isolated profile and does not claim coverage of omitted profile derivation.
- `session_key` is nullable in the schema and optional in the creation API. The existing helper uses the real nonempty `id` when this key is NULL. This is not a fabricated identity and does not establish SP14 missing-identity coverage.
- `create_session` requires a `session_id` argument annotated `str`; the inspected insert forwards it without an explicit nonempty-string validation. The schema says `id TEXT PRIMARY KEY`, not an explicit `NOT NULL`/nonempty CHECK. `get_session` selects by ID and `_session_row_dict` preserves the selected columns; a missing lookup returns None, not a malformed session row. These findings do not prove all malformed identities impossible. No malformed-ID persisted/read path was executed; SP14 remains UNVERIFIED rather than asserting NOT_APPLICABLE from the PRIMARY KEY declaration alone.
- Authoritative lifecycle uses nullable `ended_at REAL` and `end_reason TEXT`; no legacy `status` column exists. Creation leaves terminal fields NULL; `end_session` stamps `time.time()` and reopening clears them. These APIs do not expose an arbitrary `ended_at` input. The inspected schema has no explicit lifecycle type CHECK, so API inspection is not proof against every malformed stored value. No supported malformed lifecycle execution was established: SP15 remains UNVERIFIED, not NOT_APPLICABLE.
- `project_detached` was not changed: `ended_at is None` maps to ACTIVE; numeric authoritative ended snapshots map to CLOSED. Existing helper identity/type rejection remains intact. No SQL corruption, custom schema, monkeypatched legacy values or production semantic changes were used.

### Authoritative paired evidence

All authoritative tests use real `hermes_state.SessionDB`, temporary `tmp_path` storage and the existing isolated `HERMES_HOME` fixture. Fixture setup uses supported creation APIs. After writer close, reads use a real read-only SessionDB handle. Existing MATCH assertions are unchanged.

| Scenario | Classification | Exact test and evidence |
|---|---|---|
| SP13 missing optional fields | MATCH | `test_sp13_real_omitted_optional_arguments_preserve_nulls_and_defaults`: real `create_session("optional", "local", profile_name="offline")` omits optional arguments. Actual `get_session` has a valid ID, NULL key/parent, NULL optional metadata and integer defaults. Projection retains identity, derives a valid key from that same ID, preserves NULL/default adapter fields, remains ACTIVE, repeats equivalently and leaves the source/reread unchanged. |
| SP14 missing required identity | UNVERIFIED | No authoritative malformed-identity row was projected. The helper-only rejection test below is not legacy parity; absence of a schema/API impossibility proof also prevents NOT_APPLICABLE. |
| SP15 malformed lifecycle/status | UNVERIFIED | No real malformed `ended_at` row was produced through supported APIs. Helper-only invalid-type rejection is not paired parity. No fabricated `status` field or direct SQL was used to manufacture a MATCH. |
| SP17 repeated projection determinism | MATCH | `test_sp17_real_repeated_projection_is_deterministic`: `_legacy_lineage_fixture` creates actual parent/child rows. Two projections of the same authoritative child and one of a fresh equivalent read have equal complete core objects and adapter envelopes. ID/key/parent/status/source are checked explicitly. Core objects, metadata dictionaries and envelopes are independent; clearing the first projection leaves the other two and a fresh projection equal. Source and reread remain unchanged. |
| SP18 detached-output mutation isolation | MATCH | `test_sp18_real_detached_mutations_leave_source_and_peer_projection_unchanged`: two projections of the same real child row are independent. Changing core source metadata, replacing adapter profile and removing its timestamp cannot alter the original source snapshot, a fresh authoritative read, or the other projection. |

SP17's helper implementation uses only the loaded values and fixed core defaults, not a clock/random/environment lookup. The test compares complete outputs and demonstrates independent mutable containers; it does not claim cross-version or every-environment determinism. SP18's authoritative rows contain SQLite scalars/serialized JSON text. No nested authoritative mutable-object isolation is claimed; only the mutable core metadata and adapter envelope actually present at this boundary are exercised.

No-write proof for SP13/SP17/SP18: baseline main-DB SHA-256 is captured after fixture writer close; it is unchanged during read/projection and after reader close. Original row snapshots equal authoritative rereads, including after detached mutations. This is bounded database-content evidence, not a guarantee of no SQLite sidecar activity or production mutation fencing.

### Helper-only robustness evidence — excluded from MATCH totals

- `test_sp14_helper_only_invalid_identity_rejection_is_repeatable_and_nonmutating`: hand-built missing/None/empty/non-string IDs each raise exactly `ValueError("missing_required_identity")` on two attempts; inputs remain unchanged. No valid Session or fallback identity is returned.
- `test_sp15_helper_only_invalid_ended_at_rejection_is_repeatable_and_nonmutating`: hand-built string/list/dict `ended_at` values each raise exactly `ValueError("malformed_lifecycle")` repeatedly, without source mutation. This covers those invalid types, not every conceivable malformed numeric value.
- Earlier hand-built helper tests and the generic twenty-label smoke test are not promoted into authoritative SP14/SP15 evidence. SP17/SP18 classifications use the real SessionDB tests listed above.

### Validation receipts

| Check | Exact command | Executed result |
|---|---|---|
| Focused | `C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra` | 35 passed, 0 failed, 0 skipped; 1 `PytestCacheWarning` (WinError 183); 18.37s; exit 0 |
| Full core | `C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra` | 217 passed, 0 failed, 0 skipped; 1 `PytestCacheWarning` (WinError 183); 20.04s; exit 0 |
| Compileall | `C:\Python314\python.exe -m compileall hermes_core` | PASS; exit 0 |
| Canonical | `& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'` | 12 files, 217 passed, 0 failed, 100% complete; 34.3s; 24 workers; exit 0. No skips/retries reported; successful per-file output is summarized, so zero warnings is not claimed. The initial ~191 estimate is not the executed count. |
| Safe legacy selector | `C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra` | COLLECTION ERROR; 0 behavioral tests executed; 1 collection error, 2 `PytestCacheWarning` warnings (WinError 183); 1.62s; exit 1 |

Safe-selector failure: `ModuleNotFoundError: No module named 'concurrent_log_handler'`, through `tests/tui_gateway/test_session_resume_db_ownership.py → tui_gateway/server.py → agent/conversation_loop.py → hermes_logging.py → concurrent_log_handler`. This is an infrastructure/collection blocker, not a behavioral assertion failure. Cache warnings concern `.pytest_cache/v/cache` creation and are not behavioral failures. Supported Python/installed pytest were used with approved access; no dependency installation or bypass was performed.

### Current parity and readiness

| Evidence generation | MATCH | INTENTIONAL_DELTA | UNVERIFIED | NOT_APPLICABLE |
|---|---:|---:|---:|---:|
| Sprint 1.5.14 targeted SP13/SP14/SP15/SP17/SP18 | 3 | 0 | 2 | 0 |
| Current SP1–SP20 after Sprint 1.5.14 | 10 | 0 | 10 | 0 |

Current MATCH: SP1, SP2, SP7, SP9, SP12, SP13, SP17, SP18, SP19, SP20. UNVERIFIED: SP3–SP6, SP8, SP10, SP11, SP14, SP15, SP16. SP8 was not reclassified; SP16 was not targeted. Historical totals/receipts remain in their original generations.

- B1 — `PARTIALLY_ADDRESSED`: deterministic detached projection does not establish transactional mutation fencing.
- B2 — `PARTIALLY_ADDRESSED`: NULL/default preservation and isolation coverage improve; remaining persistence/projection requirements remain unresolved.
- P — `PARTIAL`: ten scenarios remain UNVERIFIED, including authoritative malformed-state evidence.
- B — `PARTIAL`: safe legacy collection, complete regression/performance/rollback and operational evidence remain blockers.

Phase 0 remains `AUTHORIZED`; Phase 1, Phase 2, Phase 3 and Phase 4 remain `NOT_AUTHORIZED`. Production migration remains **NO-GO**. Production runtime, real user DBs, production HERMES_HOME, credentials/network, provider/tool/delivery effects, wiring, ownership transfer and shadow/canary/cutover were not used. Changes are confined to appended test/evidence content; no commit or push.

## Sprint 1.5.15 — Authoritative Lease Boundary Discovery & Projection Parity

Actual implementation baseline: `0451fdd5d3092d9d753690f28cabf62ac484800b` (verified HEAD; initially clean tree). The older `630bb3b4316cc95ecfccb406fbf20ce3811579b3` in the canonical prompt was not checked out. No reset, production change, commit or push. Prior evidence generations are preserved unchanged.

### Discovery and boundary decision

Decision established before adding tests: **B — separate durable lease authority**, with an additional **C — gateway/process-local serialization layer**. The durable authority is `session_turn_leases` in the real SessionDB database, not the `sessions` row returned by `get_session()`. A is therefore not the selected boundary, and D is false for legacy turn ownership. The existing session-row projection remains untouched; its default core lease fields are not evidence of legacy ownership.

Inspection included the Sprint 1.5.10 scenario definitions; `session-persistence-projection.md`, `session-persistence-hardening-evidence.md`, this evidence document, `runtime-ownership-map.md`, `runtime-audit.md`; `hermes_core/domain/session.py`, `application/session_service.py`, `ports/persistence.py`; core session, persistence-hardening and offline projection tests. Repository searches covered lease/turn lease, owner, generation, fencing, acquire/release, heartbeat, TTL/expires/deadline and stale-owner concepts. Broad Python searches were narrowed to the SessionDB family, gateway and agent consumers, and lease-specific tests. Exact authoritative files found:

- `hermes_state_common.py::SCHEMA_SQL`: `session_turn_leases`, `compression_locks`, `gateway_heartbeats` and session columns.
- `hermes_state_compression.py::SessionCompressionMixin`: `_session_turn_lease_key_on_conn`, `_session_turn_lease_key`, `try_acquire_session_turn_lease`, `acquire_session_turn_lease`, `refresh_session_turn_lease`, `release_session_turn_lease`; module helper `_claim_lease_row`.
- `hermes_state_messages.py`: `_TURN_LEASE_ROW_SQL`, `_stale_holder`, holder-fenced transcript write path, conversation generation and transcript-generation logic.
- `hermes_state.py::_compression_lock_holder_process_is_dead`: only provably dead local PIDs allow early reclaim; the current PID and unstructured holders are not declared dead.
- `agent/turn_facade_lease.py`: `admit_durable_turn_lease`, `DurableTurnLease`, TTL/refresh behavior. Inspected only; no agent, periodic scheduler or watcher was started.
- `gateway/turn_lease.py`: `SessionTurnLeaseRegistry`, `_SessionLease`, `TurnLeaseToken`; `gateway/session_state.py`: turn token/generation and persistent `run_generation`; `gateway/run_turn.py::_hmwa_acquire_turn_lease`: passes run generation into the token. Inspected only, not instantiated as a gateway runtime.
- `hermes_state_registry.py`, `hermes_state_sessions.py`: connection generation, git generation and session expiry distinctions. `tests/state/test_session_turn_lease.py` supplied the narrow supported legacy selector; gateway/run-agent lease test paths were found but not selected for runtime execution.

### Exact representations and semantic limits

| Concept | Authoritative representation / finding |
|---|---|
| Durable scope | `conversation_id TEXT PRIMARY KEY`; resolved inside the write transaction by walking compression lineage. Explicit forks remain independent. Not necessarily a routing key or the current compressed segment ID. New parity tests use a root session only. |
| Durable owner | `holder TEXT NOT NULL`, an opaque turn token. Runtime admission constructs `pid=<pid>:turn=<relay_turn_id>:platform=<platform-or-unknown>`. The tests use supported current-process `pid=...:turn=...` tokens and acquire only temporary fixture leases. |
| Acquisition/fencing | `_claim_lease_row` reclaims expired/dead holders, INSERT OR IGNOREs, then confirms the holder in one transaction. Refresh and release qualify by conversation ID plus holder. Transcript writes likewise check the holder in their write transaction. No durable integer epoch column exists here. |
| Lease expiry | `acquired_at REAL NOT NULL`, `expires_at REAL NOT NULL`; acquisition computes `time.time() + max(0.1, float(ttl_seconds))`. Default TTL is 300s. Runtime refresher defaults to 60s. Expiry makes a row reclaimable; matching-holder refresh/transcript renewal can revive a still-unclaimed row. This is not immediate deletion or unconditional revocation. |
| Waiting vs expiry | `acquire_session_turn_lease` uses a monotonic wait deadline (default 1800s); this is the contender's waiting budget, not the owner's TTL. Gateway registry wait timeout defaults to 5s and also does not expire its owner. |
| Unleased state | No durable row for the resolved conversation key, including after owner-qualified DELETE. A retained expired row is a different/reclaimable state, not the tested absent-row representation. Process-local registry uses no holder/unlocked idle state. |
| Process-local owner | `TurnLeaseToken.owner_key`, `generation`, `released`; registry release checks exact token identity. Tokens serialize resolved session IDs within one event loop and can rebind after rotation. |
| Malformed constraints | Durable holder/acquired_at/expires_at are NOT NULL; API rejects falsy session ID/holder and converts/clamps TTL. No explicit finite-number/type CHECK or mandatory holder-format validation establishes universal malformed-state exclusion. Registry coerces generation with `int()`. This does not prove SP16 impossible. |

Generation concepts are not interchangeable:

- Core `Session.generation` is session-state/persistence CAS version; candidate mutation is adopted by `SessionService` only after persistence success.
- Core `lease_generation` increments on acquisition; release/close require owner plus matching ownership epoch. Core has no lease deadline/TTL field.
- Durable legacy fencing uses holder-token equality, not an integer acquisition counter. Same-holder reacquisition may succeed; core reacquisition while owned is rejected. The bounded SP3 observation does not claim complete transition equivalence.
- Gateway `TurnState.lease_generation` / `TurnLeaseToken.generation` carry the caller's monotonic process-local `run_generation`; this is not a demonstrated durable core lease epoch.
- `conversation_generations` advances conversation boundaries; message/transcript generations concern replay/compaction. Git metadata generation fences git updates. SessionDB registry/file generations identify resource lifetimes. Migration-controller generation fences migration transitions. None is substituted for core lease generation.
- Session `ended_at`, `expiry_finalized` and idle/daily session expiry are not turn-lease expiry. `gateway_heartbeats` tracks backend liveness; it is not the `session_turn_leases.expires_at` clock. Compression locks are another table and scope, not the turn lease being compared.

### Executable evidence and classifications

Added only `tests/hermes_core/test_offline_lease_parity.py`. Its fixture sets temporary HERMES_HOME before importing real SessionDB and creates a temporary root session with explicit profile/key. All mutations use real SessionDB APIs; `read_lease` uses SQLite `mode=ro` SELECT solely to observe the repository-created table. No direct SQL mutation/custom schema, fake legacy lease rows, production ownership transfer, gateway startup or lease refresher/watchdog occurs. The paired core side uses real `Session.acquire_lease` / `release_lease`; no CAS fake is presented as legacy authority.

| Scenario | Classification | Evidence and exact scope |
|---|---|---|
| SP3 lease owner | MATCH | `test_sp3_real_durable_holder_matches_core_exclusive_owner`: supported real acquisition produces a durable holder equal to the actual core-acquired owner; a different contender is rejected on both sides; wrong-owner release leaves the durable row and core owner intact. This is owner/exclusivity parity for a live root-session lease, not epoch/TTL/full-acquisition-policy parity. |
| SP4 lease generation/version | UNVERIFIED | Durable table has no integer lease epoch; gateway uses process run generation. No exact translation to core ownership epochs was established or tested. Absence of a column alone is not a global NOT_APPLICABLE proof. |
| SP5 lease expiry present | UNVERIFIED | SP3 test observes the real acquired/expires timestamps and their 300s difference. Real TTL exists, so NOT_APPLICABLE would be wrong. Core has no equivalent expiry state/behavior; no paired expiry normalization, timeout/reclaim execution or intentional-delta contract was established. |
| SP6 no lease | MATCH | `test_sp6_real_absent_and_released_lease_matches_core_unowned`: actual durable row absence before acquisition and after supported release agrees with core owner None; intermediate acquired owner agrees; post-release refresh fails and repeated legacy release leaves no row. Session remains open. Core default alone is not used as proof. |
| SP16 malformed lease data | UNVERIFIED | Constraints/guards were inspected, but no authoritative malformed-state parity executed and universal impossibility was not proven. No corruption, fabricated dictionary or replacement schema was used. |

The separately executed existing `test_turn_lease_refresh_and_release_are_owner_fenced` confirms real legacy owner-fenced refresh/release/reacquisition. It is supporting legacy evidence, not additional paired epoch/expiry evidence. Existing core CAS tests remain core-only. These tests intentionally mutate temporary fixture leases; they are not described as no-write projection tests or multi-process/restart proof.

### Validation receipts

| Check | Exact command | Result |
|---|---|---|
| Focused lease parity | `C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_lease_parity.py --confcutdir=tests/hermes_core -q -ra` | 2 passed, 0 failed/skipped; 1 `PytestCacheWarning` (WinError 183); 1.75s; exit 0 |
| Full core | `C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra` | 219 passed, 0 failed/skipped; 1 `PytestCacheWarning` (WinError 183); 20.72s; exit 0 |
| Compileall | `C:\Python314\python.exe -m compileall hermes_core` | PASS; exit 0 |
| Canonical core | `& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'` | 13 files, 219 passed, 0 failed, 100% complete; 34.3s; 24 workers; exit 0 |
| Narrow legacy lease selector | `& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/state/test_session_turn_lease.py -k test_turn_lease_refresh_and_release_are_owner_fenced'` | 1 file, 1 passed, 0 failed, 100% selected run complete; 9.5s; 24 workers; exit 0. Other tests in the file were not executed. |
| Safe TUI legacy selector | `C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra` | COLLECTION ERROR; 0 behavioral tests executed; 1 collection error, 2 `PytestCacheWarning` warnings (WinError 183); 1.49s; exit 1 |

TUI collection import chain: test → `tui_gateway/server.py` → `agent/conversation_loop.py` → `hermes_logging.py` → `concurrent_log_handler`; `ModuleNotFoundError: No module named 'concurrent_log_handler'`. This is an infrastructure/collection blocker, not a failed behavioral assertion. Cache warnings concern `.pytest_cache/v/cache` creation, not behavioral correctness. Canonical summaries report no retries/skips, but suppress successful per-file warning detail; no zero-warning claim is made. Estimates ~193/~19 are not executed test counts. No dependencies were installed or bypassed.

### Totals, readiness and authorization

| Generation | MATCH | INTENTIONAL_DELTA | UNVERIFIED | NOT_APPLICABLE |
|---|---:|---:|---:|---:|
| Sprint 1.5.15 targeted SP3/SP4/SP5/SP6/SP16 | 2 | 0 | 3 | 0 |
| Current SP1–SP20 after Sprint 1.5.15 | 12 | 0 | 8 | 0 |

MATCH: SP1, SP2, SP3, SP6, SP7, SP9, SP12, SP13, SP17, SP18, SP19, SP20. UNVERIFIED: SP4, SP5, SP8, SP10, SP11, SP14, SP15, SP16. Existing projection tests and lifecycle mapping were not modified; prior MATCH observations pass. Unrelated classifications and historical totals remain unchanged.

B1 remains `PARTIALLY_ADDRESSED`: bounded real owner fencing improves evidence but does not establish a complete transactional adapter, epoch mapping or multi-process recovery. B2 remains `PARTIALLY_ADDRESSED`: complete persistence/projection coverage is absent. P remains `PARTIAL` with eight unresolved scenarios. B remains `PARTIAL`: TUI collection and full regression/performance/rollback/operational evidence remain incomplete.

Phase 0 is `AUTHORIZED`; Phase 1–4 are `NOT_AUTHORIZED`. Production migration remains **NO-GO**. No production runtime/schema changes or production resources were used. No commit or push.
