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
