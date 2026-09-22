# Migration Readiness Reassessment — Sprint 1.5.9

Дата оценки: 2026-09-22. Проверенная ревизия: `a52a668311ba306daf7ac68e1619b10e7966cd7d`.

## Executive summary

Изолированный `hermes_core` теперь имеет исполняемые контракты для session, persistence, delivery, capability/approval, routing/fallback, migration controller и lifecycle/recovery/rollback. Канонический запуск прошёл: 11 файлов, 182 теста, 0 failures. Это доказывает изолированные contract invariants и границы fake-портов, но не доказывает подключение к Hermes runtime.

Production migration остаётся **NO-GO**. Текущий runtime сохраняет authoritative ownership. Core не подключён к gateway, SessionDB, delivery ledger, provider resolver или tool registry; durable persistence, runtime recovery, parity с legacy и representative performance остаются неподтверждёнными.

## Baseline inspected

Проверены исходный gate и evidence Sprint 1.5.0–1.5.8: `migration-readiness-gate.md`, adapter boundary, session projection/hardening, delivery recovery, capability enforcement, provider routing/fallback, migration controller, differential parity и lifecycle/recovery/rollback документы; `hermes_core/`; `tests/hermes_core/`; runtime owners `gateway/`, `tui_gateway/`, `hermes_state*`, `agent/`, `tools/`.

`docs/architecture/capability-policy-engine.md` является ранним design-only документом. Актуальным core evidence для capability является `capability-approval-enforcement.md` и `capability-approval-hardening-evidence.md`; это различие сохранено.

## Canonical validation result

| Command | Result | Boundary |
|---|---|---|
| `python -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q` | 182 passed, 1 `PytestCacheWarning` | direct isolated core run |
| `python -m compileall hermes_core` | completed successfully | import/bytecode check only |
| `scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core` | 11 files, 182 passed, 0 failed, no retries | canonical per-file runner |
| `scripts/run_tests.sh tests/tui_gateway/test_session_resume_db_ownership.py` | INFRA_ERROR, 0 tests collected | missing `concurrent_log_handler` during import |

The direct and canonical core runs used Windows/Python 3.14.3/SQLite 3.50.4. The direct run emitted a cache-path warning; it does not change test assertions. The legacy selector was safe to attempt because its tests use `_RecordingDB` fakes, but dependency collection failed before execution. No production DB, credentials, network, provider, tool or delivery effect occurred.

## Gate reassessment

| Gate | Previous | Current | Evidence | Remaining gap |
|---|---|---|---|---|
| A — Architecture contracts | FAIL | PARTIAL | Core domain/ports and the eight architecture contracts are inspectable; controller, session CAS, delivery ambiguity, capability binding and route-plan semantics align at isolated scope | Older design docs contain superseded gaps; no production adapter mapping or complete runtime field contract; contradictions must be resolved before adapter work |
| C — Core contracts | UNVERIFIED | PASS | Canonical `tests/hermes_core`: 182 passed across 11 files, including C1–C4 and Sprint 1.5.8 scenarios | PASS is limited to isolated core contracts; no runtime integration or real infrastructure adapter |
| R — Legacy regression | UNVERIFIED | UNVERIFIED | Existing harness and applicable suites were inspected; safe focused selector failed collection with missing `concurrent_log_handler` | Install/prepare the supported dependency environment and run applicable G1–G7 baseline/candidate receipts; current core receipt is not legacy evidence |
| P — Differential parity | UNVERIFIED | PARTIAL | DP1–DP22 are explicitly `UNVERIFIED`; DP23 is `NOT_APPLICABLE`; DP24 records core suite reference. Totals: MATCH 0, INTENTIONAL_DELTA 0, UNVERIFIED 23, NOT_APPLICABLE 1 | No legacy/core paired execution or verified MATCH; no bounded adapter fixture receipt |
| L — Lifecycle/recovery/rollback | UNVERIFIED | PARTIAL | LR1–LR24 executed; SR1–SR5 executed, SR6 UNVERIFIED; DR1–DR6 executed; rollback rehearsal, kill switch and fail-closed failover tested | Evidence is isolated control-plane/fake-repository only; no operational startup/recovery, durable audit, runtime ownership or route-failure cleanup |
| S — Security/capability | FAIL | PARTIAL | `invoke_protected` validates bound grants, approval, principal/context, arguments, expiry/revocation and denies before executor; 21 capability tests pass | Legacy `invoke` remains an unprotected compatibility path; durable revocation/lifetime, surface authorization, adapter mapping and OS containment remain runtime-owned |
| M — Performance | UNVERIFIED | UNVERIFIED | No representative latency, throughput, memory, DB contention, provider/tool overhead or prompt-cache budget receipt exists | Define a bounded slice and collect baseline/candidate p50/p95/p99 and resource measurements before any phase increase |
| B — Evidence completeness | FAIL | PARTIAL | Reproducible core commands, exact count 182, contract docs, parity totals, lifecycle matrix and production-isolation boundary are recorded | Legacy, performance, durable adapter, paired parity, approval record and full bounded-slice evidence pack are missing |

The gate vocabulary is exactly `PASS`, `PARTIAL`, `FAIL`, `UNVERIFIED`. `C=PASS` does not imply migration readiness because `READY = A ∧ C ∧ R ∧ P ∧ L ∧ S ∧ M ∧ B` and multiple mandatory gates are not PASS.

## Blocker reassessment

| Blocker | Previous | Current | Evidence | Remaining gap | Next action |
|---|---|---|---|---|---|
| B1 — session mutation not transactionally fenced | OPEN | PARTIALLY_ADDRESSED | `SessionService` candidate + `conditional_save`; P1–P10, SR1–SR5 green with deterministic CAS fake | No real atomic SessionDB operation; `RuntimeApplication.plan()` can retain lease after route failure; empty owner is not rejected | Define and validate a read-only detached projection first, then separately specify atomic adapter command and route-failure cleanup |
| B2 — persistence projection incomplete | OPEN | PARTIALLY_ADDRESSED | `session-persistence-projection.md`; core-owned fields and adapter-owned profile/transcript/WAL fields are explicit; round-trip tests pass | Runtime row, profile/source/origin, expiry, transcript, routing home, WAL/handle ownership are not represented by core | Produce a field-preservation mapping and real temporary SessionDB read receipt; no writes or schema change |
| B3 — delivery outcome loses recovery semantics | OPEN | CLOSED_AT_CORE_CONTRACT_LEVEL | `DeliveryResult`, `DeliveryTransportError`, UNKNOWN_ACK/ABANDONED, metadata propagation and DR1–DR6 tests (including transport ambiguity) resolve the original core outcome defect | Gateway ledger/async adapter, provider reconciliation, idempotency and crash-window behavior remain runtime/adapter-owned | Preserve the ledger as sole effect owner and collect adapter parity evidence before any send path |
| B4 — capability/approval not enforced by core | OPEN | CLOSED_AT_CORE_CONTRACT_LEVEL | `invoke_protected` performs bound grant/approval validation and denies before executor; immutable identity/argument binding, expiry/revocation and 21 passing S tests resolve the original protected-core enforcement defect | Legacy `invoke` is explicitly an unprotected compatibility API; runtime surface authorization, durable revocation and OS containment remain outside this contract | Keep protected execution as the only candidate migration boundary; separately inventory legacy callers before any effect migration |
| B5 — provider routing does not own existing behavior | OPEN | PARTIALLY_ADDRESSED | Deterministic `RoutePlan`, opaque credential references, explicit fallback classes and R tests; production resolver inspected | Lazy precedence, pools, recovery, profile affinity and prompt-cache behavior remain runtime-owned/unverified | Build offline legacy-vs-core route-record fixtures without repeating credential-bearing resolution |
| B6 — migration controller architecture only | OPEN | CLOSED_AT_CORE_CONTRACT_LEVEL | `MigrationController` is implemented as a control-plane contract; LR1–LR24 and M1–M24 execute phase graph, fencing, kill switch, drain, audit and fail-closed failover invariants | No trusted durable controller state, runtime drain observation, audit persistence or ownership execution | Keep controller offline; any durable/runtime controller work requires a separately bounded slice and adapter contract |
| B7 — regression/rollback evidence incomplete | OPEN | PARTIALLY_ADDRESSED | 182-test core receipt, parity matrix, lifecycle rehearsal and rollback contract | Legacy receipt blocked by dependency collection; no paired baseline/candidate, operational rollback, performance or approver record | Repair isolated test environment and execute the applicable legacy matrix; then collect one bounded slice evidence pack |

`PARTIALLY_ADDRESSED` is a blocker label from the original prompt, distinct from readiness gate statuses.

## Differential parity summary

`MATCH: 0`
`INTENTIONAL_DELTA: 0`
`UNVERIFIED: 23`
`NOT_APPLICABLE: 1`

The core tests execute core behavior; their `PASS` result is not a parity `MATCH`. Legacy provenance is explicitly `UNVERIFIED` in the parity observations. DP23 is `NOT_APPLICABLE` because no legacy migration controller exists.

## Lifecycle/recovery summary

`LR`: 24/24 isolated scenarios executed.
`SR`: SR1–SR5 executed; SR6 retry-after-recovery remains `UNVERIFIED`.
`DR`: DR1–DR6 executed, including real `DeliveryTransportError` ambiguity.
`rollback`: eight applied control-plane steps, generations 1–8, with ownership restored to LEGACY.
`kill switch`: generation-fenced, idempotent and blocks forward transitions.
`failover`: explicitly `FAILOVER_NOT_ALLOWED/failover_unverified`, no mutation.
`operational gaps`: no durable audit, startup/recovery, aggregate drain, runtime ownership execution, provider reconciliation, or production adapter receipt.

## Security summary

The protected core path binds grant identity to principal, session, turn, call, tool and canonical arguments; approval is bound to the same action, and invalid/expired/revoked/future grants fail closed before executor invocation. This supports `S=PARTIAL` at isolated core-contract scope. It does not authorize production security: legacy `ExecutionService.invoke` remains an explicitly unprotected compatibility path, runtime surfaces and output authorization remain outside this contract, durable revocation is absent, and in-process controls are not an OS sandbox.

## Performance summary

No representative benchmark exists. The 0.36-second direct test duration and 15.4-second canonical runner wall time measure test execution and process isolation, not production latency or resource cost. `M=UNVERIFIED`.

## Production phase authorization

| Phase | Authorization | Prerequisites / current evidence / missing evidence / safety reason |
|---|---|---|
| Phase 0 — offline/isolated validation | AUTHORIZED | Core contracts and deterministic fakes are green; continue only with no production effects. A bounded slice, reproducible receipts and isolation controls remain required for each activity. |
| Phase 1 — detached/read-only shadow | NOT_AUTHORIZED | A future read-only detached projection is architecturally allowed, but no bounded slice, real field-preservation receipt, parity period or performance budget has been completed. |
| Phase 2 — bounded shadow comparison | NOT_AUTHORIZED | Requires paired legacy/core outcomes, no unexplained P0/P1 divergence, runtime surface/security receipts, performance budget and rollback receipt; absent. |
| Phase 3 — canary ownership | NOT_AUTHORIZED | Requires Phase 2, durable ownership fencing, runtime drain/kill-switch integration, on-call and rollback evidence; absent. |
| Phase 4 — production cutover | NOT_AUTHORIZED | Requires all mandatory gates PASS, full cohort parity, security/performance/restore/rollback evidence and approved owner record; absent. |

## Smallest safe next engineering slice

Exactly one slice is recommended: **offline legacy-vs-core detached session projection parity harness**.

**Scope:** one bounded, read-only session projection for a temporary, synthetic legacy SessionDB fixture. Compare normalized identity, lifecycle, parent lineage, lease fields and explicitly preserved adapter metadata against the detached `hermes_core.domain.session.Session` projection.

**Non-goals:** no `SessionService` writes, acquire/release/close, schema migration, WAL repair, production `HERMES_HOME`, gateway wiring, provider/tool/delivery calls, ownership transfer or feature flag.

**Entry criteria:** current core suite remains green; fixture fields and authoritative legacy owner are enumerated; a supported dependency environment exists; scope, profile and rollback owner are written down.

**Implementation boundary:** a test-only or offline harness beside the architecture evidence, using real imports and a temporary database/fixture, with no runtime import registration and no mutation of production files or database.

**Test/evidence requirements:** field-preservation table; profile/source/routing-home separation; detached-object proof; no-write proof; missing/expired/closed row behavior; exact command, SHA, OS/Python/SQLite, executed/skipped/retried counts and normalized parity totals. No `MATCH` unless legacy provenance is actually executed and equivalent.

**Rollback/isolation requirements:** delete only the temporary fixture after the run; keep production `HERMES_HOME` and runtime untouched; abort on any attempted write or external effect; retain raw receipt without secrets.

**Exit criteria:** all selected fields have an explicit owner; read-only fixture run is reproducible; no unexplained core/legacy divergence; unresolved fields remain `UNVERIFIED`; evidence is sufficient to reassess B1/B2/P without implying adapter readiness.

## Remaining migration blockers

The decisive blockers are missing real legacy execution, missing paired parity, incomplete runtime field and adapter contracts, no operational lifecycle/recovery receipt, no durable audit/controller state, no representative performance baseline, incomplete runtime capability/surface enforcement, and no approved bounded production slice. SR6 retry semantics and provider/delivery reconciliation remain explicitly unverified.

## Final readiness conclusion

The reassessment improves isolated evidence: C is PASS; A, P, L, S and B are PARTIAL; R and M remain UNVERIFIED. B1, B2, B5 and B7 remain `PARTIALLY_ADDRESSED` because their original defects still include missing transaction/projection/legacy-regression behavior. B3, B4 and B6 are `CLOSED_AT_CORE_CONTRACT_LEVEL`: their original isolated core-contract defects have executable contract/test resolution, while runtime, adapter, durability and operational gaps remain open. Phase 0 is AUTHORIZED for offline/isolated validation only; Phases 1–4 are NOT_AUTHORIZED. Production migration remains **NO-GO**.

No production runtime behavior, database, adapter, traffic, credential, provider, tool or delivery path was changed. No commit or push was performed.
