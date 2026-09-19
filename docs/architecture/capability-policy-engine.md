# Capability Policy Engine

Дата: 2026-09-19. Ревизия анализа: `e94fb188bda83db7e85864e3fb5e247a544d0a04`.

Архитектурный результат Sprint 1.4.4. Задание найдено в `.ai/prompts/sprint-1.4.4-capability-policy-engine.md`; этот документ является его выходом. Ниже определены предлагаемые контракты, а не реализованный engine. Runtime остаётся авторитетным. Код, тесты, registry, approvals, resolver и схема БД не изменяются.

Основа: [SECURITY.md](../../SECURITY.md), [AGENTS.md](../../AGENTS.md), инструкции областей [tools](../../tools/AGENTS.md), [agent](../../agent/AGENTS.md), [gateway](../../gateway/AGENTS.md), [runtime audit](runtime-audit.md), [adapter boundaries](adapter-boundary-design.md). Анализ статический и выборочный; он не доказывает корректность каждого platform/plugin path.

## 1. Current Authorization Landscape

| Область | Проверенный источник и действующая ответственность | Граница будущего контракта |
|---|---|---|
| Внешний caller | `gateway/authz_mixin.py`: source, adapter/profile policy, caller allowlists; SECURITY §2.6 требует авторизацию dispatch, approval и output | Session ID — routing handle, не доказательство прав. Сохранить проверки каждой поверхности |
| Profile isolation | `agent/secret_scope.py`, gateway scoped reads: ContextVar и запрет заимствовать default secrets при multiplex scope miss | Policy input получает проверенный profile; отсутствие scope нельзя исправлять глобальным environment |
| Tool exposure | `tools/registry.py`, `model_tools.py`, session toolsets | `check_fn` с process-wide TTL проверяет availability/opt-in, не права конкретной сессии |
| Tool execution | `agent/tool_executor.py`, inline executors, `model_tools.py::handle_function_call` | Сохранить последовательные, параллельные и segmented paths, middleware, hooks и tool-specific gates |
| Approval | `tools/approval.py`, `approval_context.py`, `write_approval.py`, ACP guard | Текущий requester/session/turn/call context и разрешение пользователя принадлежат существующим механизмам |
| Provider | `hermes_cli/runtime_provider.py`, `agent/auxiliary_client.py`, credential sources/pools | Resolver владеет precedence и credentials; наличие ключа само по себе не определяет proposed policy authorization |
| Session persistence | `hermes_state_sessions.py`, `hermes_state_registry.py`, SessionDB | Profile/lineage и хранение истории не являются grant store. Lease и версия сессии не подтверждают права caller |
| Новый core | `hermes_core/ports/tools.py`, `application/execution_service.py`, `ports/providers.py` | Пока нет capability engine. Строка `capability_grant` и boolean `approved` не являются проверенным разрешением |

`ExecutionService` проверяет непустое имя и передаёт вызов порту, в том числе при `approved=False`. `ToolExecutionContext` frozen, но не содержит principal, profile, audience, policy revision, expiry или approval receipt. `ProviderPort` не задаёт authorization context. Это ограничения подключения, не основание объявлять уже существующую защиту.

В `model_tools.py` request middleware может менять аргументы; ошибки request middleware и pre-tool hooks обрабатываются с продолжением пути. ACP edit guard имеет отдельную обработку отказа. Поэтому будущую обязательную policy-проверку нельзя просто поместить в необязательный hook и считать её fail-closed. Execution middleware также получает dispatch callback: финальный enforcement должен проверять фактически переданные handler аргументы.

По SECURITY Hermes — single-tenant personal agent. Все callers внутри разрешённого множества адаптера одинаково доверены. Предлагаемая модель описывает область операции и её происхождение; она не вводит tenant RBAC или изоляцию пользователей. Разделение недоверенных callers по правам потребовало бы отдельного изменения trust model; сейчас для этого предусмотрены отдельные instances.

Единственная заявленная граница против adversarial LLM — ОС. Terminal backend ограничивает shell/file paths, но не весь Python process, plugins, hooks, MCP и host code execution. Policy engine внутри процесса остаётся механизмом предотвращения ошибок.

## 2. Capability Model

Capability — именованное право выполнить определённую операцию над ограниченным ресурсом. Capability identity (`tool.invoke`, например) отличается от grant identity: первая обозначает вид права, вторая — конкретную выдачу. Ни имя capability, ни знание grant ID не дают права предъявителю автоматически.

Предлагаемый grant содержит:

| Поле | Контракт |
|---|---|
| `grant_id`, `capability_id` | Уникальная opaque ссылка и зарегистрированный тип операции; неизвестный тип не разрешается |
| `issuer`, `subject`, `audience` | Доверенный владелец выдачи, instance/profile/agent scope и исполнитель, которому адресован grant |
| `scope` | Profile, source/platform, session и при необходимости turn/task; конкретный tool/resource либо provider/model/endpoint/purpose |
| `constraints` | Ограничения действия: backend/workspace, разрешённая destination, argument binding, budget или use count только там, где есть исполнитель ограничения |
| `issued_at`, `expires_at` | Проверяемый срок; отсутствие срока не трактуется как бессрочное разрешение |
| `policy_revision`, `revocation_epoch` | Версия политики выдачи и состояние отзыва; не смешивать с SessionDB generation или lease generation |
| `parent_grant_id` | Только для явно разрешённого делегирования с сужением scope и срока |

Оператор определяет policy через доверенную конфигурацию; будущий issuer на composition boundary выдаёт grant после существующей surface authorization. Модель, tool result, plugin hook message или переданная caller строка не являются источником выдачи. In-process plugin технически имеет полномочия процесса: контракт не обещает защиту от злонамеренного plugin.

Validator проверяет запись у issuer/доверенного хранилища, subject, audience, scope, срок, отзыв и operation binding. Enforcement выполняет действующий owner эффекта. Отозвать grant может оператор/issuer; lifecycle owner закрывает grants своей сессии/turn и дочерние grants. Agent может запросить сужение/отзыв, но не расширить права самостоятельно.

По умолчанию grant ограничен текущим run/session; approval receipt — конкретным действием. Завершение scope, отмена turn, отзыв родителя, смена profile или истечение срока прекращают возможность нового dispatch. Persisted transcript не восстанавливает grant. После restart нужна повторная выдача по текущей policy; durable grants и распределённый отзыв требуют отдельного контракта хранения, которого сейчас нет.

Внутрипроцессный deadline измеряется монотонными часами; внешний expiry проверяется по доверенному времени с явно определённой допустимой погрешностью. Неопределённая валидность означает DENY. Срок дочернего grant не превышает родительский, права задаются пересечением, а не объединением. Одноразовое использование требует атомарного claim, а не локального `used=True` после эффекта.

### Каталог capability-контрактов

Имена ниже проектные, registry записей и новые APIs этим документом не создаются.

| Capability | Owner | Input context | Decision | Enforcement point | Risk |
|---|---|---|---|---|---|
| `surface.dispatch` | Текущий adapter/authz owner | Проверенный caller, profile, source, актуальная admission policy | ALLOW либо DENY; approval не заменяет admission | До запуска agent work | Вход через чужой session ID или default allowlist |
| `surface.output` | Текущий gateway/transport owner | Caller authorization, profile, recipient/chat/thread, output scope | ALLOW либо DENY | До выдачи истории, stream или send | Утечка результата другому получателю |
| `approval.resolve` | Текущий surface + approval owner | Проверенный responder, pending request, action binding, expiry | ALLOW либо DENY | До изменения pending approval | Подмена ответа, replay и разрешение чужого действия |
| `tool.invoke` | Текущий agent/tool pipeline | Agent, session/turn/call, grant, настоящее имя tool, финальные arguments, backend | ALLOW / DENY / REQUIRE_APPROVAL | До handler/inline effect, после преобразований | Bypass через bridge, inline tool или поздний worker |
| `provider.access` | Текущий resolver/client owner | Profile, provider, endpoint, API mode, purpose, grant | ALLOW / DENY / REQUIRE_APPROVAL при настроенном интерактивном режиме | До credential-bearing запроса к route | Смена trust destination при fallback |
| `model.invoke` | Текущий main/aux client owner | Авторизованный route, canonical model, purpose и request scope | ALLOW / DENY / REQUIRE_APPROVAL по явной policy | До каждого inference attempt | Обход model/purpose ограничений через alias или auxiliary route |
| `credential.use` | Текущий credential source/pool owner | Profile, opaque reference, разрешённые provider/endpoint и audience | ALLOW либо DENY; без выдачи raw secret caller | При разрешении reference и перед использованием transport | Cross-profile key, credential forwarding чужому host |

Shell/file writes — ограничения `tool.invoke` по ресурсу и backend, а не обещание отдельной sandbox. Использование credentials не разрешает их чтение/экспорт моделью. Approval может удовлетворить только заранее предусмотренное условие действия, но не создать отсутствующее provider/tool право.

## 3. Policy Decision Contract

### Неизменяемый вход

Предлагаемый `PolicyInput` — глубоко неизменяемый snapshot, построенный доверенным caller adapter. Frozen оболочка с изменяемым dictionary недостаточна. Snapshot включает:

- **session:** instance/profile, session ID и routing key отдельно, turn/task/call/request IDs, lifecycle fence;
- **user:** проверенный principal и источник authentication/admission; для cron — явный service principal оператора, не выдуманный пользователь;
- **agent:** текущий agent ID, parent/delegation chain и ограниченный scope;
- **operation/tool:** capability ID, каноническое имя, финальные аргументы или безопасная ссылка на их immutable snapshot, backend/resource; для provider — route/model/purpose;
- **capability:** проверенный grant snapshot, issuer, scope, deadline, revocation epoch;
- **approval:** отсутствует либо проверенный receipt с request ID, responder, action binding, решением и сроком;
- **risk level:** trusted classification (`low`, `medium`, `high`, `unknown`), reason и version классификатора; значение модели не считается оценкой;
- **policy/time:** revision, проверенное время и доступность интерактивного approval channel.

Неизвестный risk не означает ALLOW: он приводит к REQUIRE_APPROVAL только если policy явно допускает такую ветку и канал доступен, иначе DENY. Risk score не отменяет hard deny. User и session нужны для attribution/routing, а не для создания несуществующей multi-tenant границы.

### Выход и порядок решений

`PolicyDecision` концептуально содержит `decision_id`, `effect`, стабильный `reason_code`, policy revision, operation binding, expiry и обязательные условия enforcement. Это проект данных, не новый класс в `hermes_core`.

| Effect | Семантика |
|---|---|
| ALLOW | Только указанное действие разрешено при выполненных ограничениях; это не bypass существующих tool/backend checks |
| DENY | Эффект не запускается; различимы причины missing context, scope mismatch, revoked, expired, explicit deny и policy unavailable |
| REQUIRE_APPROVAL | Выполнение приостановлено. Существующий approval owner получает запрос; после ответа требуется новая оценка |

Приоритет: невалидный контекст/admission → DENY; explicit deny, отзыв, scope mismatch или expiry → DENY; затем проверка обязательных approval constraints; ALLOW возможен только после выполнения всех условий. Несколько grants не складываются в более широкое право без явно заданной композиции. Ошибка evaluator — DENY с отдельной причиной, а не ALLOW или бесконечный retry.

Receipt связывает ответ с profile, session/turn/call, capability, final operation snapshot и policy revision. Смена аргументов, destination, tool, route или policy делает прежнее решение непригодным; повторное вычисление не должно повторно запускать hooks с эффектами. DENY и REQUIRE_APPROVAL никогда не передаются handler как обычное разрешение. Timeout/cancel/disconnect не считаются согласием; unattended path не превращает запрос approval в auto-allow.

После ожидания проверяются актуальные admission/grant/revocation/lifecycle facts. Между проверкой и началом действия owner должен атомарно подтвердить dispatch/one-use claim. Отзыв после начатого необратимого эффекта не отменяет уже сделанное; существующий cancellation mechanism применяется по возможности, результат учитывается без повторного исполнения. Exactly-once внешних эффектов этот контракт не обещает.

Audit record содержит IDs, причину, revision и outcome без raw arguments, prompts, ключей или токенов. Digest аргументов не гарантирует сокрытие низкоэнтропийного секрета: такие поля исключаются из публичного audit; binding хранится в доверенном scope. Нельзя сериализовать credential-bearing resolver result в decision log.

## 4. Tool Authorization Rules

Будущий flow: surface admission → trusted context → раскрытие bridge до реального tool → существующие преобразования запроса и guards → оценка финального действия → при необходимости existing approval → повторная проверка → существующий dispatch → existing result recording. Все inline, sequential, parallel, segmented и nested tool paths должны иметь эквивалентную точку enforcement.

`enabled_toolsets`, capability grant и availability — разные понятия. Tool schema берётся из session surface; `HERMES_DESKTOP` и process-wide `check_fn` не определяют права сессии. Отсутствующий grant не означает unrestricted, даже если отдельный legacy параметр сейчас использует `None` с таким смыслом. Legacy mapping требует явной доверенной policy, не преобразования любого `None` в ALLOW.

`approved=True` из текущего core нельзя принимать вместо receipt. Сохраняются terminal/write/ACP checks; новый evaluator не создаёт второй prompt на одно и то же действие. До интеграции нужно согласовать, какой existing owner выпускает receipt и как tool-specific policy связывает его с фактическим действием. Current `approved=False` не эквивалентен DENY: это отсутствие доказательства, которое должен обработать будущий контракт.

Request/pre-tool/execution middleware могут менять действие. Проверка проводится на финальных данных у dispatch callback; любое последующее изменение требует переоценки. Hooks вызываются существующим owner ровно в предусмотренных местах; policy не использует произвольный plugin hook как доверенный issuer. Side effects самого in-process hook не изолируются policy engine.

Workers получают явный immutable context и корректно скопированные/reset ContextVars. Thread pool, nested tools, subagents и background completion не наследуют более широкую ambient policy. Отменённый batch не начинает поздний effect; approval control проходит обе existing gateway busy guards. Grant делегата ограничен родителем, session context и backend.

Отзыв может блокировать новый dispatch без изменения cached system prompt или tool schemas посреди разговора. Изменения конфигурации поверхности следуют cache-aware правилам AGENTS; нельзя ради policy refresh перестраивать прошлый контекст. Видимость tool не обещает вечного права его исполнить.

## 5. Provider Authorization Rules

Provider authorization не заменяет routing. Existing resolver сохраняет lazy precedence, custom/local aliases, pools, OAuth и fallback; main и auxiliary purpose разрешаются своими существующими путями. Policy проверяет согласованную комбинацию provider, canonical model, endpoint, API mode, profile и purpose.

Предлагаются две стадии: проверка допустимости запрошенного provider/purpose до чувствительных действий resolver и проверка конкретного resolved route до credential use/inference. Current resolver может обращаться к auth/pool уже при resolution. Поэтому нельзя обещать полностью чистую pre-resolution проверку или делать второй production resolve для shadow comparison. Разделение стадий требует отдельного дизайна реального call path; до него live integration заблокирована.

`provider.access` допускает конкретный provider/destination; `model.invoke` ограничивает модель и purpose; `credential.use` разрешает только использование нужного секрета доверенным client owner. Все применимые условия нужны одновременно. Наличие provider grant не разрешает произвольный model, endpoint или auxiliary task. Alias нормализует существующий resolver, не новая таблица policy engine.

Opaque credential reference связан с profile, source, audience и разрешённым endpoint. Reference не является raw key, произвольным file path или env variable от модели. OAuth refresh и pool rotation остаются у current owners; новый key допустим только в прежней разрешённой области. Scope miss в multiplex режиме закрывает путь без fallback к default profile environment.

Каждый fallback/retry, изменяющий route/model/credential scope, проверяется заново перед запросом. DENY не классифицируется как transient provider outage и не должен запускать обход ограничений через fallback. Existing fallback owner может выбирать другие кандидаты только в согласованной разрешённой области; конкретная обработка policy denial — обязательное решение до integration. Повтор на том же route всё равно проверяет expiry/revocation.

Approval provider/model допустим лишь как явно настроенный interactive flow; сейчас наличие такого общего flow не установлено. Для cron/auxiliary без канала approval будущий REQUIRE_APPROVAL заканчивается отказом/приостановкой задачи по согласованному контракту, не скрытым переключением на другой provider. Secrets не попадают в model context, policy options, repr и audit.

## 6. Migration Boundaries

Порядок дополняет [adapter design](adapter-boundary-design.md) и [regression execution plan](regression-harness-execution.md). Все действия в таблице — будущие implementation-задачи.

| Этап | Owner до → после | Условие перехода и откат |
|---|---|---|
| Зафиксировать контракты | Current runtime → без изменения | Согласовать issuer/validator, receipt, deep immutability, denial/error mapping, profile scope; сейчас создан только документ |
| Изолированная проверка evaluator | Current runtime → тот же owner эффектов | Deterministic inputs, deny precedence, clock/revocation/replay cases; evaluator не исполняет tools и не разрешает credentials |
| Mapping context/receipt | Existing context/approval owners → те же | Реальные imports и temp profiles; current core bool/string не подменяют доказательства; откат mapping без изменения storage |
| Один tool consumer | Existing pipeline → pipeline с проверенным gate | Все его inline/bridge/worker paths, final args, single prompt/effect, cancellation; stop intake/drain, затем вернуть прежний path |
| Один provider consumer | Existing resolver/client → те же с gate | Pre/post-resolution effects, credentials, auxiliary/fallback и endpoint matrix; rollback wiring без отката rotated secrets |
| Расширение surfaces | Current adapters → те же | Dispatch/output/approval admission на каждой поверхности; обязательный lifecycle/rollback receipt |

Нельзя объявлять engine активным, пока существует незакрытый путь к эффекту в выбранном consumer. Нельзя использовать глобальный cache ALLOW по имени tool, process environment или session ID. Revocation store, atomic claim и policy version ownership должны быть выбраны до production integration; текущая SessionDB схема не расширяется этим спринтом.

Проверки будущей реализации выполняются через `scripts/run_tests.sh`, с реальными imports и временным `HERMES_HOME`, без source-text snapshots. Требуются behavioral cases: spoofed/missing principal, two-profile isolation, expired/revoked/delegated grant, argument mutation после approval, replay/concurrent claim, policy exception, unauthorized output/approval, inline/bridge path, поздний worker, fallback на запрещённый endpoint, secret sentinel в logs, отсутствие duplicate effects и сохранение prompt cache.

ОС-зависимые проверки исполняются на соответствующей ОС с принятыми markers. Unit mocks не доказывают интеграцию boundaries. Статический анализ не даёт PASS этим gates; тесты и evals в этом спринте не запускались.

При откате остановить новые операции и обработать текущие существующими drain/cancel owners. Не повторять исполненные tools, не освобождать чужие leases и не переносить approval receipts на новый turn. Прежний runtime path возвращается только с явным пониманием возврата к его прежним гарантиям; rollback не должен молча обходить обязательную operator policy.

## 7. Security Risks

| Риск | Контрактная мера и предел |
|---|---|
| Capability принимают за sandbox/RBAC | Сохранить SECURITY trust model; OS isolation и отдельные instances для разделения недоверенных пользователей |
| Confused deputy через caller-provided grant | Доверенный issuer, subject/audience/profile binding и admission до выдачи |
| TOCTOU и replay | Повторная проверка после ожидания, operation binding, atomic claim; начатый внешний эффект не обратим автоматически |
| Hook меняет аргументы после ALLOW | Enforcement у final dispatch; hooks с произвольным Python всё равно доверены как часть процесса |
| Права протекают между workers/profiles | Immutable context, explicit propagation/reset и scoped secret reads; запрет ambient fallback |
| Provider fallback уносит credential/prompt | Проверка каждого фактического route и credential audience; denial не считается обычным outage |
| Отзыв конфликтует с prompt caching | Блокировать dispatch, не переписывать историю/system prompt и schemas автоматически |
| Policy outage разрешает выполнение | Fail-closed evaluator с отдельной причиной; не подключать как fail-open middleware |
| Approval недоступен в cron | Явный unattended policy outcome; отсутствие оператора не является согласием |
| Grant восстановлен из transcript или старой БД | История не authority; новая выдача после restart, отдельный будущий durable lifecycle contract |
| Audit раскрывает секреты | Минимальные IDs/reasons, безопасные bindings, запрет raw credentials/arguments; redaction не считается containment |

До интеграции остаются открытыми: формат доверенного receipt и его связь с текущими approval modes; место обязательного final gate для каждого executor; issuer/revocation ownership при нескольких процессах; двухстадийный provider flow; точное отображение DENY/REQUIRE_APPROVAL в существующие результаты. Эти вопросы блокируют подключение соответствующего пути, но не требуют реализации в документационном спринте.

Критерии этого спринта: capability model и policy contract описаны; owners и migration risks выделены; действующий runtime остаётся авторитетным; создан только этот документ, без изменений production, тестов, `.ai/` или схемы БД.
