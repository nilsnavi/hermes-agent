# Migration Readiness Gate

Дата оценки: 2026-09-21. Проверенная ревизия: `106c4989ac68cd16032d7a853d988b61eaf43330`.

Этот документ является результатом Sprint 1.5.0 и отвечает на вопрос: безопасно ли начинать перенос production-компонентов Hermes в `hermes_core`? Оценка основана на текущем коде, архитектурных контрактах, существующей тестовой инфраструктуре и зафиксированных пробелах. Она не выполняет миграцию и не подключает новый слой к runtime.

## 1. Readiness Decision

**Решение: NO-GO для любой production runtime migration.**

На проверенной ревизии нельзя передавать `hermes_core` ownership сессий, delivery, provider routing, tool execution или общего runtime lifecycle. Архитектурное направление определено, но обязательные контракты неполны, production adapters и migration controller не реализованы, direct regression coverage `hermes_core` отсутствует, а runtime/eval/rollback gates не имеют актуальных PASS receipts.

Допустимый scope сейчас: **GO только для подготовительной работы**, которая не меняет production ownership или поведение: согласование контрактов, реализация изолированных unit/contract tests в отдельном спринте, создание test fixtures, offline differential harness и получение baseline receipts. Это не разрешение на shadow-вызовы production adapters, limited traffic или включение migration flags.

Решение fail-closed. Отсутствующий, устаревший, flaky или инфраструктурно неисполненный обязательный receipt не считается PASS. Зелёный узкий subset не компенсирует непроверенную P0-границу.

### Decision record

| Поле | Значение |
|---|---|
| Decision ID | `MRG-1.5.0-2026-09-21` |
| Scope | Любая первая production migration из current runtime в `hermes_core` |
| Verdict | `NO-GO` |
| Authoritative owner | Существующий runtime во всех областях |
| Migration phase allowed | Только Phase 0 observation без новых production hooks; offline/isolated validation |
| Migration phases denied | Shadow с effectful adapters, limited traffic, ownership transfer, legacy removal |
| Evidence revision | `106c4989ac68cd16032d7a853d988b61eaf43330` |
| Re-evaluation trigger | Закрыты применимые blockers и собран полный evidence pack для одного bounded slice |

## 2. Evidence Reviewed

Проверены:

- изолированные domain, application services и Protocol ports в `hermes_core/`;
- [application-layer foundation](application-layer-foundation.md);
- [regression harness plan](regression-harness-plan.md) и [execution plan](regression-harness-execution.md);
- [adapter boundary design](adapter-boundary-design.md);
- [capability policy engine](capability-policy-engine.md);
- [runtime migration controller](runtime-migration-controller.md);
- [runtime ownership map](runtime-ownership-map.md), `AGENTS.md` и `SECURITY.md`;
- наличие канонического `scripts/run_tests.sh`, существующих session/WAL/delivery/tool/provider suites и eval frameworks.

Статическая проверка на этой ревизии не нашла прямых ссылок на `hermes_core` в `tests/`. Это не означает, что текущий runtime не покрыт тестами: существующие suites защищают многие legacy-инварианты. Это означает, что соответствие нового domain/application/port слоя этим инвариантам пока не доказано исполняемыми контрактными тестами.

В рамках Sprint 1.5.0 тесты и evals не запускались. Ранее задокументированный import/compile check foundation подтверждал только импортируемость на другой момент времени и не является текущим runtime readiness receipt. Ни один документ-план сам по себе не считается доказательством PASS.

## 3. Mandatory Gate Model

Readiness оценивается для конкретного migration slice, а не для абстрактного «Hermes 2.0». Slice обязан указывать component, operation, surface, profile scope, current/future owner, эффект, точку commit, rollback path и contract revision. Общий GO без этих полей запрещён.

Итоговое правило:

```text
READY(slice) = A ∧ C ∧ R ∧ P ∧ L ∧ S ∧ M ∧ B
```

где:

- `A` — архитектурные и adapter-контракты полны;
- `C` — `hermes_core` contract tests прошли;
- `R` — применимая legacy regression suite прошла до и после изменения;
- `P` — differential parity доказана без двойных эффектов;
- `L` — lifecycle, recovery и rollback подтверждены;
- `S` — security/capability/profile boundaries подтверждены;
- `M` — performance/resource budget подтверждён;
- `B` — baseline, receipts и change boundary полны.

Любое значение `FAIL`, `UNVERIFIED`, `FLAKY` или `INFRA_ERROR` у обязательного P0 gate делает `READY=false`. `SKIP` допустим только с доказательством неприменимости к выбранному slice и ссылкой на ownership map.

### Gate status on the assessed revision

| Gate | Текущий статус | Основание |
|---|---|---|
| A — Architecture contracts | FAIL | Контрактные разрывы перечислены ниже; production adapter interfaces не способны сохранить все runtime outcomes |
| C — Core contracts | UNVERIFIED | В `tests/` нет прямого `hermes_core` coverage; C1–C4 из execution plan не реализованы/не исполнены |
| R — Legacy regression | UNVERIFIED | Suites существуют, но актуального полного receipt для этого readiness decision нет |
| P — Differential parity | UNVERIFIED | Нет реализованного pure shadow/differential harness и результатов для bounded slice |
| L — Lifecycle/recovery/rollback | UNVERIFIED | Нет production controller, drain/rollback implementation или rehearsal receipt |
| S — Security/capability | FAIL | Capability policy — design only; текущие core grant/approval поля не обеспечивают enforcement |
| M — Performance | UNVERIFIED | Нет baseline/candidate measurements и заранее утверждённого budget |
| B — Evidence completeness | FAIL | Нет выбранного production slice, adapter SHA, gate receipts и approver record |

## 4. Blocking Findings

### B1 — Session mutation is not transactionally fenced

`SessionService.acquire()` изменяет Python-объект, затем вызывает `save()`. `SessionRepository.save(session)` не принимает expected generation/CAS и не выражает atomic acquire/release/close. Два процесса могут принять решение на устаревших projections; ошибка persistence оставляет объект уже мутированным.

Дополнительно `RuntimeApplication.plan()` захватывает lease до provider resolution и не освобождает его при route exception. Пустой owner не запрещён контрактом. Core `generation`, `lease_generation`, runtime run generation и DB file generation нельзя считать одним счётчиком.

**Блокирует:** любой mutating session adapter и любую orchestration migration.

**Условие закрытия:** согласованный atomic repository command/result contract, rollback объекта при persistence failure, route-failure cleanup и multi-process stale-owner tests с реальным временным SessionDB.

### B2 — Persistence projection is incomplete

Core `Session` не представляет полный runtime row: profile/source/origin, expiry, transcript/usage/compression lineage и routing-home semantics не имеют типизированного отображения. Полный `save(Session)` может потерять поля, которыми владеет legacy storage. Handle acquisition/release и WAL/file-generation ownership не выражены портом.

**Блокирует:** write adapter. Read-only detached projection может быть будущим первым кандидатом только после отдельного evidence pack.

**Условие закрытия:** explicit field mapping, borrowed/acquired handle policy, один release на acquire, preservation tests, routing-home/profile isolation и WAL/replacement recovery receipts.

### B3 — Delivery outcome cannot preserve current recovery semantics

Core различает `pending/attempting/delivered/failed`, но не представляет unknown ACK или abandoned. `DeliveryService` переводит любое transport exception в `FAILED` и возвращает только state, теряя `external_id`, `retryable` и error classification. Порт не несёт trusted destination/profile/message ID и синхронен относительно async gateway transports.

**Блокирует:** delivery adapter, retry ownership и любой real-send shadow.

**Условие закрытия:** typed definitive/ambiguous outcome, metadata propagation, async scheduling contract, destination binding и crash tests до/после ACK с существующим ledger/recovery owner.

### B4 — Capability and approval are not enforced by core

`ExecutionService` вызывает port и при `approved=False`. `capability_grant` — необработанная optional string, а boolean approval не связан с principal, profile, session/turn/call, final arguments, expiry, revocation или policy revision. Нет обязательного final enforcement point после middleware/bridge transformations.

По `SECURITY.md` approval и capability остаются in-process controls и не заменяют OS isolation или external surface authorization.

**Блокирует:** tool adapter, inline/registry unification и migration любого mutating tool path.

**Условие закрытия:** immutable trusted policy input, ALLOW/DENY/REQUIRE_APPROVAL contract, action-bound receipt, fail-closed final gate и parity tests для inline, bridge, sequential, concurrent и segmented execution.

### B5 — Provider routing contract does not own existing behavior

`ProviderRouter` только делегирует `ProviderPort.resolve`. В core нет текущей lazy precedence, main/auxiliary distinction beyond purpose, credential-pool recovery, fallback policy или prompt-cache behavior. Порт не выражает profile scope и credential-reference lifecycle. Существующий resolver может обновлять auth/pool state, поэтому повторный shadow resolve не является доказанно read-only.

Также `RouteDecision` использует `route_purpose`; ранее сформулированный контракт именовал `purpose`. Скрытый alias в adapter не является согласованием API.

**Блокирует:** provider adapter, fallback ownership и provider shadow execution.

**Условие закрытия:** единый naming contract, explicit profile/credential audience, route/fallback outcome model, preservation of lazy precedence/cache semantics и differential matrix без повторного credential-bearing effect.

### B6 — Migration controller is architecture only

Определены phases, flags, audit и rollback principles, но отсутствуют implementation, trusted configuration source, revision/CAS state, single-owner execution token, decision audit, kill switch, drain integration и tested failover. Включать migration flags нечему и запрещено текущим спринтом.

**Блокирует:** Phase 1 production shadow, Phase 2 limited traffic и последующие phases.

**Условие закрытия:** отдельная реализация после утверждения contracts, собственные contract tests и fail-closed integration на одном read-only bounded slice.

### B7 — Regression and rollback evidence is incomplete

Существующие tests покрывают важные legacy paths, но execution plan фиксирует недостающие P0 scenarios: end-to-end session lifecycle, multi-process WAL/replacement, aggregate worker drain, crash around delivery ACK, tool-path parity и provider cross-product. Актуальные G1–G7/C1–C4 receipts отсутствуют. Нет rollback rehearsal с проверкой sessions, handles, leases и unresolved delivery obligations.

**Блокирует:** любой production ownership transfer.

**Условие закрытия:** реализованные invariant tests, канонические запуски через `scripts/run_tests.sh`, applicable evals и успешный rollback rehearsal на той же candidate revision.

## 5. Component Readiness Matrix

| Component | Earliest admissible next step | Production migration readiness | Главные блокеры |
|---|---|---|---|
| Session | Contract tests и read-only detached projection на temp storage | NO-GO | B1, B2, B7 |
| Persistence/SQLite | Adapter design validation на real temp DB, без schema change | NO-GO | B1, B2, B7 |
| Delivery | Outcome/async contract tests с fake transport | NO-GO | B3, B6, B7 |
| Tools | Pure policy/evaluator tests и context mapping | NO-GO | B4, B6, B7 |
| Provider | Offline route-record mapping fixtures | NO-GO | B5, B6, B7 |
| Runtime lifecycle | Aggregate ownership/drain baseline tests | NO-GO | B1, B6, B7 |

Ни один компонент сейчас не допускается к Phase 2 limited traffic. Phase 1 допустима только как offline/isolated shadow без production effects. Наблюдение существующих logs/tests не должно требовать нового runtime hook в рамках этого решения.

## 6. Required Evidence Pack for Re-evaluation

Повторная оценка проводится для одного bounded slice и включает:

1. **Scope record:** component/operation/surface/profile, current и future owner, точка эффекта, authoritative state, failure/retry owner и полный список consumers.
2. **Contract record:** versioned input/output/error/lifecycle/security semantics; закрытые применимые B1–B7; никакие гарантии не спрятаны в `metadata`, optional strings или ambient environment.
3. **Change record:** baseline SHA, candidate SHA, полный diff, dependency/schema/API statement и подтверждение отсутствия неожиданных owners.
4. **Core receipt:** C1–C4 для применимого слоя, включая negative/concurrent/error paths.
5. **Legacy receipt:** применимые G1–G7 на baseline и candidate через `scripts/run_tests.sh`; executed/skipped/retried counts и первый failure.
6. **Parity receipt:** одинаковые normalized decisions/outcomes на pinned fixtures без двойных writes, provider calls, tools, approvals или sends.
7. **Lifecycle receipt:** startup/recovery, intake stop, aggregate drain, interrupt/deadline, lease/handle release и cold resume.
8. **Security receipt:** surface auth, profile/secret isolation, capability decisions, approval replay/expiry/revocation и сохранение заявленной OS boundary.
9. **Performance receipt:** заранее утверждённые correctness-preserving p50/p95/p99, throughput, memory/DB contention и prompt-cache cost budgets на baseline/candidate.
10. **Rollback receipt:** rehearsal с возвратом старого owner, сохранением формата данных, корректными leases/handles и без потери/повтора unresolved obligations.
11. **Eval receipt:** только применимые paired pinned-tree evals; infrastructure failures отделены от model/behavior scores.
12. **Approval record:** владелец решения, дата, expiration, известные ограничения и точный разрешённый rollout phase/cohort.

Каждый receipt содержит command/selector, code/config/contract/policy revisions, OS/Python/SQLite, fixture/seed, exit code, durations, failures/retries, artifacts и границы доказательства. Секреты, prompts и полный пользовательский content в evidence pack не включаются.

## 7. Decision Procedure

1. Reviewer подтверждает, что slice bounded и текущий owner установлен по коду, а не только по диаграмме.
2. Применимые blockers переводятся в `CLOSED` со ссылками на code/tests/receipts; `accepted risk` не закрывает P0 correctness/security blocker.
3. Все обязательные gates вычисляются независимо. Reviewer не усредняет результаты и не заменяет missing evidence экспертной уверенностью.
4. `GO-PHASE-1` разрешает только чистый/изолированный shadow. `GO-PHASE-2` разрешает один single-owner canary при наличии kill switch и rollback receipt. Более высокая фаза требует новой оценки.
5. Решение связывается с SHA и config/contract revisions и автоматически истекает при изменении затронутого contract, adapter, owner, schema, security policy или migration controller.
6. При divergence, security failure, unexpected duplicate effect, lifecycle leak или превышении budget rollout становится `paused/rollback_pending`; автоматический fallback после частично выполненного эффекта запрещён.

### Re-evaluation template

| Поле | Требуемое значение |
|---|---|
| Slice | Конкретная операция и одна поверхность/profile scope |
| Requested phase | 1, 2 или последующая |
| Current → future owner | Однозначно указаны |
| Applicable blockers | Все `CLOSED` либо доказанно `N/A` |
| Gates A/C/R/P/L/S/M/B | Только PASS для GO |
| Effect owner | Ровно один |
| Kill switch | Проверен до точки эффекта |
| Rollback receipt | PASS на candidate SHA |
| Decision | GO / NO-GO с reason codes |
| Expiration | Дата или условие invalidation |

## 8. Validation Plan Before First Migration

Первым кандидатом может быть только read-only, неавторитетный consumer, который проецирует существующую session запись в detached core model и не меняет routing, transcript, lease, provider, tool или delivery state. Даже он требует field-preservation, profile/routing-home, handle ownership и no-write proof. Он не должен обслуживать production decision до получения GO-PHASE-2.

Последовательность подготовки:

1. Реализовать C1–C4 как behavioral contract tests без production wiring.
2. Закрыть B1–B5 на уровне явных портов/типов в отдельно утверждённых спринтах.
3. Добавить недостающие P0 regression scenarios, не заменяя существующие suites и не создавая source-text change detectors.
4. Получить baseline G1–G7 receipts на неизменённом runtime.
5. Реализовать controller/evaluator в изоляции и доказать B6 без migration flags.
6. Провести offline parity и rollback rehearsal на временном `HERMES_HOME`/fixtures.
7. Создать новый readiness record для одного slice. Только его `GO-PHASE-1` может разрешить production observation/pure shadow; Phase 2 требует отдельного решения.

## 9. Final Answer

На ревизии `106c4989ac68cd16032d7a853d988b61eaf43330` Hermes 2.0 **не готов начинать production runtime migration**. Изолированный `hermes_core` полезен как архитектурная основа, но ещё не является совместимым и проверенным владельцем runtime invariants. Текущий runtime остаётся единственным авторитетным владельцем всех компонентов.

Критерии Sprint 1.5.0 выполнены на уровне документации: решение явно, аудитируемо и fail-closed; blockers, evidence pack, re-evaluation procedure и rollback requirements определены. Никакая production migration, adapter, flag, schema/API или ownership change этим документом не выполнены.
