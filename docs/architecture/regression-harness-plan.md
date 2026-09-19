# План regression harness для Hermes runtime

Дата: 2026-09-19. План составлен по `.ai/prompts/sprint-1.4.2-regression-harness.md` на основе текущего дерева и документов `runtime-audit.md` и `baseline-protection-plan.md`. Это analysis-only документ: production-код, существующие тесты, API, схема БД и модули не изменялись; новые тесты этим заданием не создаются.

## 1. Current Test Landscape

Канонический запуск — `scripts/run_tests.sh`. Он выбирает venv с pytest, очищает окружение через `env -i`, задаёт `TZ=UTC`, `LANG=C.UTF-8`, `PYTHONHASHSEED=0`, направляет каждый файл в отдельный subprocess и один раз повторяет упавший файл. Поэтому прямой `pytest` не считается эквивалентной проверкой. Отчёт обязан различать обычный pass, pass-after-retry (flaky), timeout, infrastructure error и deselected/zero-test запуск.

Покрытие уже распределено по доменам:

- `tests/gateway/` — startup/restore, shutdown/drain, cron/API work, delivery ledger, streaming, authorization и session routing.
- `tests/hermes_state/` и `tests/state/` — shared DB registry, WAL generation, leases, persistence и file replacement.
- `tests/tui_gateway/` — session create/resume/close, DB ownership, finalize и startup orphan handling.
- `tests/run_agent/`, `tests/agent/` — conversation/fallback/compression/tool execution/provider state.
- `tests/tools/` — registry, approvals, file/terminal safety, credential and backend behavior.
- `tests/hermes_cli/` — runtime-provider resolution, fallback config, profile/auth behavior.

`evals/` дополняет, но не заменяет тесты: `codebase_navigability` измеряет форму/import/runtime cost, `compaction` — recall, `core_tool_deferral` — tool visibility A/B, `session_search_schema` — schema ergonomics, `readtool` и `browser_use` — live task behavior, `fanout_resource_bench.py` — ресурсы delegation. Harnesses требуют pinned trees, повторов и отдельного учёта инфраструктурных сбоев.

## 2. Golden Test Suite Definition

Golden suite — минимальный набор существующих проверок, который должен проходить до и после каждого runtime migration slice. Он не фиксирует количество моделей, tools или schema columns; он проверяет отношения и переходы состояний.

### Session lifecycle

Behavior: создание, resume, close, expiry, concurrent ownership, rotation и compression lineage.

Current protection: `SessionState` разделяет turn/conversation/persistent scopes; active-session lease и monotonic generation защищают stale completion; `SessionDB` хранит lineage.

Existing tests: `tests/state/test_session_turn_lease.py`, `tests/tui_gateway/test_session_resume_db_ownership.py`, `tests/tui_gateway/test_finalize_session_persist.py`, `tests/gateway/test_compression_session_id_persistence.py`, `tests/agent/test_session_rotation_flush_cold_resume_68454.py`.

Missing tests: единый end-to-end сценарий create → concurrent resume → compression rotation → close с проверкой routing index и профиля; отдельный expiry-versus-new-message race.

Risk: stale unwind может освободить новый lease, либо transcript и routing могут разойтись.

Priority: P0 — обязательный golden блок.

### Persistence, SQLite and WAL

Behavior: schema reconciliation/migrations, WAL compatibility, DELETE fallback, shared registry generation, inode replacement, recovery and FTS/message relationships.

Current protection: `hermes_state_registry.py` refcounts shared DB generations; `hermes_state_wal.py` проверяет режим и fail-closed downgrade; `hermes_state_dbfile.py` защищает probes and deleted sidecars.

Existing tests: `tests/hermes_state/test_shared_session_db_registry.py`, `tests/hermes_state/test_deleted_wal_generation_guard.py`, `tests/state/test_state_db_wal_unlink_race.py`, `tests/test_hermes_state_wal_fallback.py`, `tests/gateway/test_session_db_corrupt_fallback.py`, `tests/gateway/test_session_db_replaced_fallback.py`.

Missing tests: полный multi-process сценарий migration + concurrent reader/writer + snapshot replacement + old-generation release; проверка row/FTS/delivery counts после recovery.

Risk: потеря или смешение WAL поколения, закрытие чужого writer, частично применённая миграция.

Priority: P0.

### Gateway lifecycle and workers

Behavior: startup gate, restore timeout, queued inbound, restart, shutdown drain, cron/API/deferred workers and process ownership.

Current protection: startup/shutdown mixins, active-work aggregate, watchdog, bounded restore and explicit deferred-worker tracking.

Existing tests: `tests/gateway/test_startup_watchdog.py`, `test_startup_restart_race.py`, `test_pending_drain_race.py`, `test_gateway_shutdown.py`, `test_shutdown_executor_quiesce.py`, `test_shutdown_flush.py`, `test_shutdown_watchdog.py`, `test_cron_active_work_drain.py`, `test_api_server_active_work_drain.py`.

Missing tests: one receipt-driven scenario spanning real subprocess restart with an in-flight cron job, API run and executor worker; native Windows process ancestry when process ownership changes.

Risk: coroutine cancellation leaves real worker alive; shutdown reports idle while work runs, or desktop action kills a detached gateway child.

Priority: P0 for lifecycle changes, P1 otherwise.

### Delivery reliability

Behavior: `pending → attempting → delivered/failed`, reconnect classification, bounded retries, duplicate-visible recovery and streaming finalization.

Current protection: durable delivery ledger with owner liveness and attempt caps; stream-final contract tests.

Existing tests: `tests/gateway/test_delivery_ledger.py`, `test_delivery_ledger_producer.py`, `test_restart_redelivery_dedup.py`, `test_restart_drain_recovery_dedup.py`, `test_completion_delivery.py`, `test_stream_final_contract.py`, `test_relay_final_delivery_incident.py`, `test_post_stream_media_delivery.py`.

Missing tests: deterministic crash injection exactly before/after platform ACK for every ledger state; cross-profile delivery recovery with the same chat identifier.

Risk: silently lost response or duplicate final; permanent rejection retried as transient.

Priority: P0.

### Tool execution safety

Behavior: discovery/registration, toolset capability filtering, inline and registry dispatch, approval, hooks, sequential/concurrent execution and result persistence.

Current protection: registry schema/handler dispatch, valid-name validation, request/pre/execution middleware, approval callbacks, start-order gate and result budget.

Existing tests: `tests/tools/test_registry.py`, `tests/run_agent/test_tool_executor_contextvar_propagation.py`, `tests/tools/test_approval.py`, `test_approval_mode_parity.py`, `test_approval_interrupt.py`, `test_write_approval.py`, `tests/agent/test_tool_executor_checkpoint_paths.py`.

Missing tests: parity matrix for the same call through inline, sequential, concurrent and segmented paths; toolset visibility versus session authorization under two simultaneous profiles.

Risk: duplicate hooks, late dispatch after timeout, leaked approval context or treating `check_fn` as isolation.

Priority: P0 when executor/registry changes, P1 for unrelated refactors.

### Provider routing

Behavior: model selection, explicit/custom/local/pool/OAuth/native route precedence, fallback chain, credential isolation and API mode preservation.

Current protection: lazy resolver ladder, provider client construction, fallback index and unavailable-entry filtering, scoped profile secrets.

Existing tests: `tests/hermes_cli/test_runtime_provider_resolution.py`, `test_runtime_provider_late_binding.py`, `tests/run_agent/test_provider_fallback.py`, `test_fallback_credential_isolation.py`, `test_fallback_api_mode_preservation.py`, `tests/gateway/test_fallback_chain_reload.py`, `tests/tools/test_credential_pool_env_fallback.py`.

Missing tests: table-driven cross-product of config source × provider × endpoint × credential pool × fallback exhaustion, including auxiliary route inheritance and prompt replay bytes.

Risk: wrong provider, leaked profile credential, invalid native API mode or altered fallback order.

Priority: P0 for resolver changes, P1 for pure file extraction.

## 3. Critical Regression Matrix

| Scenario | Setup | Expected contract | Evidence |
|---|---|---|---|
| Resume while turn is active | One session, second resume request | Exactly one live owner; stale caller cannot clear current lease | lease/generation rows and final transcript |
| Compression rotation | History crosses compression boundary | Parent/child lineage and active tip resolve; no duplicate messages | session rows, message ids, compression tip |
| DB replacement during use | Open shared DB, replace inode, acquire again | Old generation retires; holders finish safely; new generation is isolated | registry identities, WAL sidecars |
| WAL incompatibility | Force journal-mode failure/uncertain readback | DELETE fallback or explicit failure per policy; no silent downgrade | actual PRAGMA mode and logs |
| Startup restore plus inbound | Delay restore, deliver message during gate | Message queues, restore slot remains unique, queue drains once | event order and session state |
| Shutdown with four work classes | Agent, cron, API and deferred worker all active | Drain counts all; interrupt only after deadline; exit state persisted | shutdown receipt and worker termination |
| Crash during delivery | Inject failure around ledger send await | Retry state follows documented marker and never silently disappears | ledger rows and outgoing messages |
| Tool batch timeout | Mixed valid/invalid concurrent calls | Valid calls complete once; abandoned calls do not dispatch late | tool results, hook trace, ids |
| Profile credential isolation | Two profiles, same provider name | Scoped miss fails closed; no default env/allowlist borrowing | captured env and route identity |
| Provider exhaustion | Primary and all fallback entries fail | Original failure is surfaced with exhausted chain; no infinite retry | route trace and retry count |

For each row, record Behavior, Current protection, Existing tests, Missing tests, Risk and Priority as in the golden definitions above. Test output must include revision, OS, Python, profile home, selected paths, retries/flaky status and skipped gates.

## 4. Missing Coverage

The main gaps are cross-component rather than absent unit assertions:

1. No single end-to-end session scenario covers routing, lease, compression lineage, persistence and final delivery together.
2. SQLite tests are strong at targeted races, but a full process-level migration/replacement/recovery receipt is not represented by one golden flow.
3. Gateway tests cover individual drain sources; combined cron + API + deferred-worker shutdown and real restart topology need a dedicated scenario.
4. Delivery tests cover ledger and stream contracts, while deterministic crash placement around transport acknowledgment remains a gap.
5. Tool tests are split by registry and approval; parity across inline/sequential/concurrent/segmented dispatch needs explicit comparison.
6. Provider tests cover important routes separately; the complete precedence matrix and auxiliary/main relationship are not one executable contract.
7. Security policy requires OS-level isolation, but ordinary unit tests cannot prove container/whole-process containment. Treat deployment posture as an explicit external gate.
8. Documentation drift exists around provider fallback and schema version; baseline reports must cite source revision and avoid using stale guides as expected values.

## 5. Test Execution Strategy

Run the smallest applicable golden slice first through `scripts/run_tests.sh`; then run the relevant domain directory; only then run the full suite. Preserve the runner's hermetic environment and per-file subprocess isolation. For Windows-specific process behavior, use host-native marked coverage and the repository's `wine2e` workflow; never patch `sys.platform`.

Persistence and routing checks use temporary profile homes, deterministic credentials and real imports. Multi-process scenarios must preserve the complete SQLite file generation context and must not operate on the user's live `state.db`. Tests that require network/provider/browser services must declare them as external prerequisites and classify unavailable infrastructure separately from product failure.

For an approved refactor, capture a baseline receipt before changes and a candidate receipt after each migration slice. Compare behavioral outcomes, not test counts or model catalog snapshots. Run applicable evals in paired pinned trees with at least the repetitions required by each README; inspect raw transcripts when a score changes. Use `codebase_navigability` and `fanout_resource_bench` for structure/resource effects, not as substitutes for correctness.

A result is `PASS` only when all selected files exit zero without hidden deselection, timeout or unresolved infrastructure error. A pass after automatic retry is `FLAKY`, requiring follow-up. Unrun security, deployment, provider-live, restore or rollback gates remain `UNVERIFIED`.

## 6. Migration Gates

1. **Baseline lock:** record commit, configuration/profile, Python/OS, selected suite and current receipts; preserve unrelated working-tree changes.
2. **Contract lock:** identify affected golden rows and their observable outputs before editing; no source snapshot or change-detector test is accepted.
3. **Ownership lock:** map every moved symbol, state owner, process/profile scope and release/close operation, including late imports and TUI rebinding.
4. **Focused gate:** all affected existing tests pass with `scripts/run_tests.sh`; failures are resolved or explicitly block migration.
5. **Cross-boundary gate:** run the relevant combined scenario (session+persistence, lifecycle+delivery, tools+approval, or routing+credentials), using real imports and temp homes.
6. **Platform gate:** execute native Windows/POSIX process checks when the change touches process identity, detachment, signals or filesystem locking.
7. **Security gate:** verify allowlists, scoped secrets and selected OS isolation posture; never treat approval or redaction as containment.
8. **Evaluation gate:** run only applicable evals, paired and repeated, with cost, latency/resource and infrastructure results reported separately.
9. **Rollback gate:** prove the previous revision can start, resume a known session, open the state DB and reconcile delivery obligations without data loss.
10. **Documentation gate:** update architecture docs and record all unrun gates. A migration is not ready while any P0 row is failing, flaky without disposition, or unverified.

This plan is documentation only. No production code, existing test, new test, refactoring, API or schema was changed.
