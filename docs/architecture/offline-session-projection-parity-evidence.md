# Offline session projection parity evidence — Sprint 1.5.10

## Executive summary

This Phase 0 slice adds a test-only projection helper and an isolated parity test harness. It never imports or wires `hermes_core` into gateway execution, never opens the production `HERMES_HOME`, and never uses a production SessionDB. The harness uses the real legacy `SessionDB` lazily against a temporary database when the supported dependency chain is available. Missing legacy dependencies cause an explicit skip; they never become synthetic `MATCH` provenance.

The supported `C:\Python314` environment executed the real legacy `hermes_state.SessionDB` against temporary test storage. The focused suite produced 24 passed tests. Only scenarios whose assertions prove legacy provenance, projection and the requested normalized relation are `MATCH`; core-only assertions remain `UNVERIFIED`. Production migration remains **NO-GO**.

## Scope and safety boundary

Only `tests/hermes_core/test_offline_session_projection_parity.py` and this evidence document are in scope. The harness uses `tmp_path` and a synthetic temporary `state.db` only. It does not acquire, release or close a real user session, invoke providers/tools/delivery, access credentials, make network calls, register with gateway/runtime, or transfer ownership. The current runtime remains authoritative.

## Repository revision

Requested starting revision: `2e91f0da7c21d85ecd4074447a6308303b6b0dc6`. The inspected checkout was at that revision before this slice. The Sprint 1.5.9 prompt's expected baseline (`bc16136...`) did not match the requested checkout and was not substituted.

## Environment and validation boundary

The host is Windows, Python `3.14.3`, pytest `8.4.2`, SQLite `3.50.4`. `yaml` import PASS; `from hermes_state import SessionDB` PASS; `concurrent_log_handler` import FAIL. The focused command was `C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra`: 24 passed, 0 failed, 0 skipped, 1 `PytestCacheWarning`, 10.35s. The full command was `C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra`: 206 passed, 0 failed, 0 skipped, 1 `PytestCacheWarning`, 28.66s. `C:\Python314\python.exe -m compileall hermes_core`: PASS. The canonical runner completed 12 test files, 206 tests passed, 0 failed, 100% complete, 19.1s, 24 workers.

The safe legacy selector `C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra` remains a collection/infrastructure blocker: 0 tests executed and `ModuleNotFoundError: No module named 'concurrent_log_handler'` through `tui_gateway/server.py → agent/conversation_loop.py → hermes_logging.py`. This is not a failed behavioral assertion. No production resource was accessed. The single `PytestCacheWarning` in the focused and full runs is recorded as a cache warning, not a behavioral failure.

## Legacy source inspected

The authoritative source is `hermes_state.SessionDB`, backed by the `sessions` table declared in `hermes_state_common.py` and initialized by `hermes_state_schema.py`. The row loader is `SessionDB._session_row_dict`; creation is `SessionDB.create_session` / `_insert_session_row`. The harness does not duplicate that schema or classify a hand-built row as legacy provenance. It calls `SessionDB(path)` on a temporary path, closes the writer, then uses `SessionDB(path, read_only=True)` for the read path.

## Field ownership matrix

| Field | Legacy representation | Core representation | Owner | Normalization | Evidence |
|---|---|---|---|---|---|
| identity | `sessions.id` | `SessionId` | CORE_OWNED | non-empty string, exact | projection helper; paired run UNVERIFIED |
| session key | `sessions.session_key` | `SessionKey` | CORE_OWNED | fallback to id only when absent | projection helper; paired run UNVERIFIED |
| lifecycle | `ended_at`/`end_reason` and legacy row state | `SessionStatus` | CORE_OWNED | only explicit active/closed values accepted by helper | malformed behavior tested; legacy pair UNVERIFIED |
| parent lineage | `parent_session_id` | `Session.parent_session_id` | CORE_OWNED | nullable `SessionId` | projection helper; paired run UNVERIFIED |
| source/profile/origin | `source`, `profile_name`, `origin_json` | outside core | ADAPTER_PRESERVED | deep-copied metadata envelope | aliasing test; paired run UNVERIFIED |
| lease owner/generation/expiry | no equivalent complete SessionDB row contract identified | absent | UNVERIFIED | never fabricated | requires adapter contract |
| creation/update/expiry timestamps | `started_at`, activity/expiry columns | absent | ADAPTER_PRESERVED | retained outside core | no paired run |
| transcript/history | messages and session counters | absent | LEGACY_ONLY | not projected | no paired run |
| routing/provider affinity | billing/routing columns | absent | ADAPTER_PRESERVED | retained outside core | no paired run |
| persistence/WAL metadata | SQLite schema/version/WAL/registry state | absent | LEGACY_ONLY | never copied into core | no paired run |
| runtime handle/process metadata | `SessionDB` connection and process state | absent | LEGACY_ONLY | must not enter output | detached invariant |

## Harness architecture

`temporary legacy SessionDB fixture → read-only SessionDB row → detached projection → normalized core/adapter comparison → parity observation`.

The source row is copied into the projection boundary. The returned core object contains only core-owned values; adapter-owned values are returned in a separate deep-copied dictionary. The core object has no DB/connection field and no source dictionary reference.

## No-write proof

The fixture is created only under pytest `tmp_path`, then reopened with `SessionDB(path, read_only=True)`. The harness records a SHA-256 digest before projection, reads through the real legacy API, projects, checks SQLite `PRAGMA data_version`, and compares the post-projection digest. The test passed, so this proves the temporary source file was unchanged for the exercised path. The projection helper calls no mutation method and performs no acquire/release/close session operation; only the temporary read handle is closed in test teardown.

## Scenario results

| Scenario | Legacy provenance | Core provenance | Result | Evidence | Notes |
|---|---|---|---|---|---|
| SP1 normal active/open | real `SessionDB.get_session("s1")` | `project_detached`, id equality assertion | MATCH | `test_sp_scenario_uses_real_legacy_or_is_explicitly_unverified[SP01]` | temporary row, actual legacy provenance |
| SP2 parent lineage | real row has no parent fixture | helper supports parent but assertion does not exercise lineage | UNVERIFIED | same parametrized test `[SP02]` | no parent scenario asserted |
| SP3 lease owner | unavailable/unsupported row field | absent | UNVERIFIED | ownership matrix | not fabricated |
| SP4 lease generation | unavailable/unsupported row field | absent | UNVERIFIED | ownership matrix | not fabricated |
| SP5 lease expiry | unavailable | absent | UNVERIFIED | ownership matrix | adapter-owned |
| SP6 no lease | unavailable | absent | UNVERIFIED | ownership matrix | no paired row |
| SP7 closed/terminal | unavailable | helper validates closed | UNVERIFIED | malformed/closed path | no paired row |
| SP8 expired | unavailable | absent | UNVERIFIED | ownership matrix | legacy representation not executed |
| SP9 profile/source/origin | unavailable | preserved envelope | UNVERIFIED | metadata aliasing test | no paired provenance |
| SP10 routing/provider affinity | unavailable | outside core | UNVERIFIED | ownership matrix | adapter-owned |
| SP11 transcript/history | unavailable | absent | UNVERIFIED | ownership matrix | legacy-only |
| SP12 unknown/adapter metadata | unavailable | deep-copied envelope | UNVERIFIED | aliasing test | no paired provenance |
| SP13 missing optional fields | unavailable | explicit fallback behavior | UNVERIFIED | projection helper | no paired provenance |
| SP14 missing required identity | unavailable | fails closed | UNVERIFIED | focused unit assertion | core-only is not MATCH |
| SP15 malformed lifecycle | unavailable | fails closed | UNVERIFIED | focused unit assertion | core-only is not MATCH |
| SP16 malformed lease | unavailable | unsupported | UNVERIFIED | ownership matrix | no fabricated lease |
| SP17 repeated projection deterministic | unavailable | deterministic helper | UNVERIFIED | focused unit assertion | core-only is not MATCH |
| SP18 detached output cannot alias source | unavailable | deep-copy assertion | UNVERIFIED | focused unit assertion | core-only is not MATCH |
| SP19 source unchanged/no-write | real temporary `SessionDB`, digest before/after | real read row + projection | MATCH | `test_real_legacy_no_write_proof_is_executable_when_dependencies_exist` | digest unchanged; data-version checked |
| SP20 multiple-session isolation | unavailable | no paired fixture | UNVERIFIED | planned by matrix | no cross-session claim |

## Parity totals

| Classification | New Sprint 1.5.10 slice |
|---|---:|
| MATCH | 2 |
| INTENTIONAL_DELTA | 0 |
| UNVERIFIED | 18 |
| NOT_APPLICABLE | 0 |

## Relationship to Sprint 1.5.7 parity evidence

Historical Sprint 1.5.7 totals remain unchanged: `MATCH 0`, `INTENTIONAL_DELTA 0`, `UNVERIFIED 23`, `NOT_APPLICABLE 1`. The new slice does not supersede or rewrite those observations. Sprint 1.5.10 totals are separately `MATCH 2`, `INTENTIONAL_DELTA 0`, `UNVERIFIED 18`, `NOT_APPLICABLE 0`.

## B1 impact

B1 remains `PARTIALLY_ADDRESSED`. A read-only projection and no-write proof cannot close transactional mutation fencing. No acquire/release/close or atomic SessionDB CAS was exercised; route-failure cleanup and empty-owner validation remain open.

## B2 impact

B2 is reduced at the documentation and bounded-read boundary: the authoritative row source was read from temporary SessionDB, and the explicit core/adapter/legacy ownership matrix is recorded. The exercised fixture does not cover the complete runtime field set or preserve every adapter field through a paired assertion, so B2 remains `PARTIALLY_ADDRESSED`.

## Gate P impact

P remains `PARTIAL`. This bounded slice produced two narrowly scoped paired `MATCH` observations (SP1 and SP19) using the real temporary legacy `SessionDB`, but the remaining session projection surface is not sufficiently verified to establish global parity or authorize a shadow.

## Gate B impact

B remains `PARTIAL`. Focused/full/canonical receipts and two bounded paired observations now exist, but the safe legacy selector has a collection dependency blocker, most SP fields remain unverified, and performance/complete regression evidence are missing.

## Remaining gaps

The supported legacy selector still needs `concurrent_log_handler` available without changing production dependency behavior. Parent lineage, lease fields, expiry, routing affinity, transcript/history, malformed legacy rows and multi-session isolation need dedicated real temporary-SessionDB assertions before they can move from `UNVERIFIED`. Unsupported fields remain explicit `UNVERIFIED` or `NOT_APPLICABLE`.

## Phase authorization

Phase 0 remains AUTHORIZED for offline/isolated validation only. Phase 1 remains NOT_AUTHORIZED; no detached production shadow was enabled. Phases 2–4 remain NOT_AUTHORIZED.

## Final conclusion

This sprint adds a bounded, deletable Phase 0 harness without runtime wiring or production effects, producing two narrowly scoped paired `MATCH` observations (SP1 and SP19) while leaving unsupported fields unverified. B1 and B2 remain `PARTIALLY_ADDRESSED`; P and B remain `PARTIAL`. Phase 1 remains `NOT_AUTHORIZED`; production migration remains **NO-GO**.
