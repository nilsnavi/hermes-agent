# Runtime Migration Controller

Дата: 2026-09-19. Ревизия анализа: `b2a74fffb39535ce0c4f2804d5791684b23570cf`.

Архитектурный результат Sprint 1.4.5. Документ определяет будущий control plane для поэтапного перевода отдельных runtime-путей на `hermes_core`. Контроллер здесь не реализован и не подключён. Действующий runtime, его данные и его владельцы остаются авторитетными.

Основа: [application-layer foundation](application-layer-foundation.md), [adapter boundary design](adapter-boundary-design.md), [regression harness plan](regression-harness-plan.md), [regression harness execution](regression-harness-execution.md), [capability policy engine](capability-policy-engine.md), [runtime ownership map](runtime-ownership-map.md), текущие `hermes_core` domain/ports/services и выбранные runtime owners. При расхождении документации и исходников приоритет имеет проверенный код.

# 1. Migration Principles

1. **Current runtime remains authoritative.** Пока ownership конкретной операции явно не передан, только действующий runtime принимает решения, изменяет durable state и выполняет внешние эффекты. Контроллер не заменяет `SessionState`, SessionDB/registry/WAL, delivery ledger, provider resolver, tool registry, approval flow или gateway lifecycle.
2. **Миграция выполняется по одному bounded slice.** Единица перевода задаётся как поверхность + профиль + операция + версия контракта, например read-only session lookup одной внутренней поверхности. Нельзя одним флагом перевести сразу CLI, gateway, TUI, cron, provider и tools.
3. **Один owner каждого эффекта.** В любой момент ровно один путь может захватить lease, записать session/transcript/ledger, вызвать provider, исполнить tool, запросить approval или отправить сообщение. Двойная запись и «первый успешный результат побеждает» запрещены.
4. **Shadow mode сравнивает только безопасные результаты.** В production допустимы повторное преобразование уже полученного immutable snapshot, вычисление чистого policy/route projection без resolver и построение плана без commit. Запрещены shadow lease acquisition, provider resolution с auth/pool effects, inference, tool execution, approval prompts, delivery и любые durable writes.
5. **Dual validation не означает dual execution.** До эффекта проверяются eligibility, contract/version/security и lifecycle fence. После единственного выполнения сравниваются нормализованные outcomes и инварианты. Второй validator не повторяет эффект и не становится вторым владельцем состояния.
6. **Fail closed для выбора нового пути.** Неизвестный флаг, отсутствующий context, несовместимая версия, устаревшая конфигурация, неготовый adapter или нездоровый controller направляют запрос в legacy только там, где это заранее признано безопасным. Если legacy fallback после частичного commit может повторить эффект, операция останавливается и передаётся существующему recovery owner.
7. **Rollback проектируется до rollout.** Для каждого slice заранее фиксируются точка невозврата, drain procedure, владелец незавершённой работы и доказательство возврата. Rollback переключает будущий intake; он не отменяет уже отправленное сообщение, provider request или tool effect.
8. **Без изменения формата данных.** Контроллер не создаёт собственную копию SessionState, ledger или schema. Его migration state — конфигурация control plane и receipts, а не новая бизнес-база. Будущая durable реализация потребует отдельного проекта хранения.
9. **Cache и security invariants сохраняются.** Переключение не изменяет system prompt/toolset посреди разговора, кроме уже разрешённых механизмов. Session ID остаётся routing handle. Capability policy является in-process контролем, а не заменой surface authorization или OS isolation.

## Shadow mode и dual validation

Контроллер строит из доверенного ingress context стабильный `MigrationEnvelope`: operation ID, component/slice, surface, profile, session/turn/call IDs, lifecycle fence, policy revision и конфигурационную ревизию. Он не включает secrets, provider tokens, полный prompt или произвольные tool arguments в audit.

В observation/shadow фазах legacy выполняет операцию как прежде. Новый путь получает только разрешённый immutable input или нормализованный legacy outcome. Сравнение выполняется по отношениям и инвариантам: одинаковый owning profile, session identity, route purpose, классификация результата и допустимость перехода. Оно не сравнивает нестабильные timestamps, случайные IDs, тексты provider errors или порядок независимых concurrent событий как точные snapshots.

Для stateful операции безопасный shadow использует изолированную fixture/temp database вне production либо pure dry-plan API с доказанным отсутствием commit. Флаг `shadow=true` сам по себе не превращает метод в read-only. Любой adapter, который вызывает существующий resolver/registry/transport, считается effectful, пока обратное не доказано тестом и контрактом.

Dual validation состоит из:

- preflight legacy-compatible проверки входа и применимости нового контракта;
- capability/security решения на фактическом контексте;
- проверки ownership/lifecycle fence непосредственно перед dispatch;
- postcondition проверки единственного результата и сохранённого состояния;
- differential comparison только с чистым oracle или заранее записанным baseline.

Расхождение создаёт audit event и блокирует повышение фазы данного slice. Оно не инициирует автоматический повтор effect и не меняет глобальный rollout остальных компонентов.

## Rollback invariant

До точки эффекта routing можно вернуть на legacy. После точки эффекта контроллер сохраняет выбранного owner до завершения или передаёт obligation существующему recovery механизму; он не запускает legacy «на всякий случай». При rollback сначала закрывается новый intake, затем draining учитывает agent turns, cron, API runs, deferred tool workers, approvals и delivery attempts. После drain переключается конфигурационная ревизия, проверяются leases/handles/obligations и только затем возобновляется intake.

# 2. Migration Controller Responsibilities

Контроллер — детерминированный selector и recorder на composition boundary. Он не входит в domain model и не импортируется `hermes_core` services. Surface controller передаёт ему доверенный context; выбранный legacy либо core application path остаётся единственным исполнителем.

## Routing decision

Концептуальный вход `MigrationDecisionInput` содержит component, operation, surface, profile, stable subject bucket, session lifecycle fence, capability decision reference, requested phase и revisions. Результат содержит выбранный path (`legacy`, `core`, `observe-only`, `blocked`), reason code, config revision и execution token. Он не содержит credential material и не меняет состояние session.

Порядок решения:

1. Проверить surface authorization и достоверность profile/context у существующего владельца.
2. Найти ровно одно правило для component/operation/surface/profile; неоднозначность блокирует core path.
3. Проверить phase, kill switch, contract versions, adapter readiness и обязательные safety gates.
4. Закрепить стабильный cohort. Bucketing использует непривилегированный стабильный subject и salt/revision оператора; caller не выбирает bucket.
5. Проверить lifecycle fence и capability outcome.
6. Выдать single-use execution token выбранному owner. Токен не является security credential вне процесса и не заменяет durable lease.
7. Зафиксировать decision audit до эффекта и outcome audit после него.

Нельзя менять owner в середине turn, delivery attempt, tool call, provider attempt/fallback chain или transaction. Новый request после безопасной границы получает новое решение.

## Feature flags

Flags являются операторской конфигурацией, не model input и не новым `HERMES_*` environment API. Предлагаемая иерархия: global kill switch → component → operation → surface → profile → cohort. Более узкое правило может только в пределах явно разрешённой rollout policy; deny/kill switch имеет приоритет.

Минимальные поля правила: `component`, `operation`, `phase`, `enabled`, `cohort_percent`, `allowed_surfaces`, `allowed_profiles`, `contract_revision`, `policy_revision`, `required_gates`, `expires_at`, `config_revision`. Срок истёк или revision неизвестна — core path запрещён. Значения читаются на безопасной границе запроса; изменение не мутирует уже выбранный owner.

Изменение tool exposure/system-prompt state подчиняется cache-aware правилам проекта: обычно действует со следующей session. Controller flag не должен незаметно заменить toolset в живом разговоре. Profile multiplex использует scope-aware config/secret context; default profile не служит fallback для secondary profile.

## Migration state

Состояние контроллера отделено от business state:

| State | Содержание | Не содержит |
|---|---|---|
| Desired configuration | Фазы, cohorts, revisions, kill switches | Sessions, messages, credentials |
| Observed readiness | Gate receipts для конкретных SHA/ОС/configuration | Самоутверждённый общий `healthy=true` |
| Active decisions | Короткоживущие operation ID, выбранный owner, fence | Копию runtime object graph |
| Drain state | Intake closed, counts по классам workers, deadline, unresolved work | Принудительное признание всех futures завершёнными |
| Rollout history | Кто/когда/почему сменил фазу, old/new revision | Secrets и полный пользовательский content |

Предлагаемая машина rollout: `disabled → observe → shadow → limited → progressive → transferred → retirement_candidate`. Из любого активного состояния возможны `paused` и `rollback_pending`; `rolled_back` требует receipt. `transferred` означает ownership только указанного slice. `retirement_candidate` не разрешает удаление legacy до Phase 4 gates.

State transition выполняется optimistic-CAS по config revision, чтобы два оператора/процесса не повысили rollout одновременно. Конкретное хранилище, API и schema не определяются этим документом.

## Compatibility checks

Перед core route контроллер требует:

- совпадение contract revision портов и adapter mapping;
- доступность обязательных context полей без magic metadata;
- совместимость profile, surface, route purpose и lifecycle generation;
- поддержку результата, включая lost lease, ambiguous delivery ACK, approval outcome и provider denial;
- подтверждённый ресурсный ownership: кто acquire/release handle, lease, worker и transport attempt;
- применимые capability-policy и external authorization gates;
- отсутствие уже начатого effect под тем же operation ID;
- receipts, привязанные к текущему code SHA, конфигурации и платформе.

Текущий `RuntimeApplication.plan()` не удовлетворяет production migration contract: он мутирует session lease до provider route, не освобождает lease при ошибке route и использует repository save без atomic expected-version/CAS. `DeliveryService` сводит исключение к failed, хотя network ACK может быть неопределённым. `ExecutionService` передаёт строку grant и boolean approval без enforcement. Эти gaps блокируют соответствующие ownership transfers; контроллер не маскирует их wrapper-логикой.

## Audit events

Стабильные типы: `migration.decision`, `migration.shadow_comparison`, `migration.gate_evaluated`, `migration.phase_changed`, `migration.drain_started`, `migration.drain_completed`, `migration.rollback_started`, `migration.rollback_completed`, `migration.divergence`.

Общие поля: event ID/time, code SHA, controller/config/policy/contract revisions, component/operation, phase, surface/profile, pseudonymous bucket, session/turn/call correlation IDs, selected owner, reason code, gate receipt IDs и outcome class. Не логируются raw secrets, credential references, prompt/history, полный tool arguments или message content. Audit telemetry остаётся локальной, пока нет отдельного opt-in для outbound telemetry.

Audit не является транзакционным владельцем business effect. Ошибка audit до обязательного security decision закрывает core path. Ошибка необязательной observability после начатого legacy effect не запускает его повторно; событие может быть восстановлено по существующему outcome receipt, если такой механизм согласован.

# 3. Migration Phases

## Phase 0: Observation only

Контроллер наблюдает границы существующего runtime: вход, выбранного owner, outcome class, lifecycle и latency. Он не вызывает `hermes_core`, не меняет маршрутизацию и не пишет бизнес-состояние. Допустим offline replay очищенных записей на fixtures.

Выход из фазы: определён bounded slice; построена карта всех его consumers/effects; baseline receipts воспроизводимы; audit не содержит secrets; есть rollback rehearsal. Любое отсутствующее ownership наблюдение оставляет slice в Phase 0.

## Phase 1: Shadow execution

Legacy остаётся единственным owner. `hermes_core` вычисляет только pure projection/validation либо работает на изолированной копии данных. Production adapters с возможными side effects не вызываются. Результаты нормализуются и сравниваются, divergences классифицируются.

Для sessions разрешён read-only detached projection; запрещены acquire/save/close. Для delivery — проверка state transition на копии, без ledger/transport. Для providers — сравнение уже разрешённого route record, без повторного resolver/auth/pool call. Для tools — validation/context planning, без hooks, approval и handler.

Выход: согласованный период/объём выборки без необъяснённых P0/P1 divergences; известные различия задокументированы как contract; overhead укладывается в gate. При divergence core shadow отключается без влияния на legacy.

## Phase 2: Limited traffic

Core path становится единственным coordinator только для одного низкорискового, явно выбранного slice и стабильного cohort. Infrastructure owner эффекта остаётся прежним через проверенный adapter. Не начинать с delivery send, mutating tools, provider fallback или multi-process lease mutation.

Каждая операция получает sticky decision на своём lifecycle scope. За пределами cohort работает legacy. Автоматический rollback допускается только до effect; после effect используется прежний recovery owner. Повышение требует canary receipts, on-call/runbook владельца и проверенного kill switch.

## Phase 3: Progressive ownership transfer

Размер cohort и число поверхностей растут только по одной оси за изменение. Application orchestration может последовательно принять session lifecycle, delivery policy, provider routing и tool pipeline лишь после их собственных контрактных gates. Physical owners SQLite/WAL, transport SDK, credentials и subprocess остаются в adapters, пока отдельно не мигрированы.

При передаче state decision удаляется второй decision owner, но legacy rollback path сохраняется и регулярно репетируется. Нельзя одновременно переносить producer и recovery consumer одной durable записи. Для каждой ступени фиксируются soak window, performance budget, divergence/error limits и rollback receipt.

## Phase 4: Legacy removal

Удаление рассматривается отдельно от переключения. Требуются 100% целевого scope на core, отсутствие legacy reads/writes/recovery jobs, завершённый retention период obligations/sessions старого формата, зеленые regression/eval/performance/security gates и доказанный cold start/restore/rollback новой версии.

Перед удалением ищутся dynamic imports, plugin contracts, docs, skills, AGENTS и compat pointers. Schema/data migration, API change и file move требуют отдельных задач. После удаления rollback означает возврат проверенной release версии и совместимого data format, а не скрытый dual runtime.

# 4. Ownership Matrix

| Компонент | Current owner | Future owner | Migration risk | Rollback |
|---|---|---|---|---|
| Session | Gateway/TUI lifecycle, `SessionState`, SessionStore routing, SessionDB/registry/WAL и runtime lease mechanisms | `SessionService` владеет lifecycle decisions; persistence adapters сохраняют DB/registry/WAL ownership | Неатомарный core acquire/save, смешение session/lease/DB generations, cross-profile routing, transcript duplication | Закрыть intake slice, дождаться/прервать его turns, освободить только его leases/handles и вернуть прежний lifecycle path; schema не менять |
| Delivery | Gateway delivery ledger/recovery и platform adapters | `DeliveryService` владеет transitions/retry policy; ledger и transport реализуют ports | Ambiguous ACK, duplicate final, streaming edit/send, второй retry owner | Не повторять attempting send; вернуть unresolved obligation существующему ledger recovery с marker/caps, затем переключить будущий intake |
| Provider | `runtime_provider`, main fallback/client lifecycle, `auxiliary_client`, credential sources/pools | `ProviderRouter` владеет route/recovery policy; credential/client adapters сохраняют secrets и SDK | Resolver имеет auth/pool effects, fallback меняет route/cache identity, credential leak между profiles | Закрепить owner текущей attempt/chain; новые requests вернуть legacy resolver, не откатывать rotation/token refresh |
| Tools | Agent validation/scheduler, inline executors, `model_tools`, registry, hooks и tool-specific approvals | `ExecutionService` владеет semantic pipeline и capability decision; handlers/backends остаются adapters | Bypass inline/bridge, двойной hook/approval/effect, late worker, ambient context leak | Stop new dispatch, drain/cancel owned workers/approvals, сохранить результаты уже выполненных effects и вернуть legacy dispatcher |
| Runtime | Gateway startup/shutdown, surface controllers, cron/API/deferred worker owners | `RuntimeApplication` координирует выбранные workflows; будущий lifecycle service агрегирует workers | Неполный drain, gateway/desktop lifetime mismatch, route failure после lease, попытка стать вторым process supervisor | Вернуть composition wiring после quiesce; восстановить прежние control/status paths, проверить process ancestry, worker counts и lease cleanup |

Future owner означает целевое решение из архитектурных документов, не существующую production реализацию. Controller никогда не становится владельцем строк SessionDB, ledger obligations, credential material или tool effects; он выбирает одного владельца и фиксирует решение.

# 5. Safety Gates

Каждый gate выдаёт receipt с code SHA, ОС/Python/SQLite, config/contract/policy revisions, командой/selector, executed/skipped/retried counts, результатом, performance samples и границами доказательства. Старый receipt не переносится автоматически на новый SHA или изменившуюся конфигурацию.

| Gate | Минимальное доказательство | Блокирует |
|---|---|---|
| Regression suite | `scripts/run_tests.sh` на применимых G1–G7/C1–C4 сценариях, real imports, temp `HERMES_HOME`; flaky и неожиданные skips видимы | Phase 2+ для затронутого slice |
| Parity checks | Нормализованное сравнение legacy/core на recorded fixtures; нет double effects; все известные divergences классифицированы | Повышение каждого slice |
| Lifecycle checks | Startup/recovery, intake stop, drain всех agent/cron/API/deferred classes, timeout/interrupt, lease/handle release, native OS process topology | Runtime/session Phase 2+ и любой широкомасштабный rollout |
| Security checks | Surface dispatch/output/approval auth, profile/secret isolation, capability ALLOW/DENY/REQUIRE_APPROVAL, expiry/revocation/replay, OS boundary не переобещана | Tools/provider/surface Phase 2+ |
| Persistence checks | Atomic fencing, stale owner, WAL fallback/replacement, cold resume, compression lineage, backup/restore без schema drift | Mutating session transfer |
| Delivery checks | pending/attempting/delivered/failed и unknown ACK, crash/reconnect, marker/caps, stream final/edit, no duplicate owner | Delivery Phase 2+ |
| Provider checks | Lazy precedence, main/aux purposes, fallback/credential refresh, endpoint audience и secret sentinel | Provider Phase 2+ |
| Tool checks | Inline/registry/bridge, sequential/concurrent/segmented, hooks single-fire, denied/timeout approvals, late worker и result persistence | Tool Phase 2+ |
| Performance checks | Baseline и canary p50/p95/p99 latency, throughput, memory, DB contention, provider/tool overhead и prompt-cache hit/cost proxy; заранее утверждённый budget | Повышение cohort/phase |
| Evals | Применимые paired pinned-tree navigability, compaction/tool/browser evals; infrastructure failures отделены от score | Phase 3/4 соответствующего scope |
| Rollback rehearsal | Kill switch, quiesce/drain, owner restoration, resume/recovery, unresolved obligations и audit continuity подтверждены | Phase 2+ и legacy removal |

Performance gate не задаёт выдуманные универсальные проценты. Бюджет фиксируется для slice до canary, учитывает холодный/тёплый путь и не скрывает ухудшение среднего хвостовой задержкой или наоборот. Shadow overhead измеряется отдельно и исчезает после отключения shadow.

Автоматический rollback может сработать по crash/error/divergence/security/performance threshold только для будущего intake. Он обязан быть monotonic и защищён от oscillation: после срабатывания slice переходит в `paused`/`rollback_pending`, а повторное повышение требует нового receipt. Security denial и unauthorized attempt не считаются обычной ошибкой сервиса и не вызывают обход через legacy.

### Acceptance Criteria

- Создан только этот архитектурный документ; production code, runtime wiring, тесты, adapters и schema не изменены.
- Current runtime остаётся авторитетным, а controller определён как selector/recorder, не второй state owner.
- Observation, safe shadow, limited traffic, progressive transfer и legacy removal имеют явные входные и выходные условия.
- Ownership и rollback определены отдельно для Session, Delivery, Provider, Tools и Runtime.
- Regression, parity, lifecycle, security и performance gates обязательны до production ownership transfer.
- Никакая production migration этим документом не выполнена; все перечисленные проверки остаются будущими gates.
