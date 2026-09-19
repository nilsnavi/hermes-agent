# Adapter Boundary Design

Дата: 2026-09-19. Исследованная ревизия: `706a09e68ef5775c7d1816261e428df3ed48ee41`.

Результат Sprint 1.4.3 Adapter Boundary Design: проект границ для будущего подключения существующих владельцев к портам `hermes_core`. Адаптеры, тесты и runtime wiring здесь не создаются. Все названия будущих адаптеров ниже — обозначения ответственности, а не новые файлы или утверждение о существующей реализации.

Основа: [foundation](application-layer-foundation.md), [ownership map](runtime-ownership-map.md), [первоначальный regression plan](regression-harness-plan.md), [уточнённый regression execution plan](regression-harness-execution.md), текущие порты и сервисы `hermes_core`, выбранные существующие runtime owners. При расхождении документации и исходников приоритет у проверенного кода. Анализ статический; runtime и harness не запускались.

## 1. Current Runtime Ownership

| Область | Действующий владелец | Что адаптеру нельзя присваивать автоматически |
|---|---|---|
| Сессии и история | `SessionDB`, `hermes_state_sessions.py`, `hermes_state_messages.py`, compression/usage siblings | Схему, семантику end/reopen, transcript ordering и compression lineage |
| DB handles | `hermes_state_registry.py`, `SessionDB.close()` | Глобальное закрытие всех handles или чужую ссылку registry |
| WAL, file generation, repair | `hermes_state_wal.py`, `hermes_state_dbfile.py`, schema/repair siblings | PRAGMA policy, unlink sidecars, самостоятельную починку или downgrade |
| Gateway routing | `gateway/session_persistence.py::SessionStore._routing_db` | Перенос общего multiplex routing index в текущий profile transcript DB |
| Lease и turn state | Runtime lease mechanisms, `gateway/session_state.py`, agent turn lease | Замену durable fencing на сравнение двух полей Python-объекта |
| Delivery | `gateway/delivery_ledger.py`, GatewayRunner recovery, platform adapters | Второй retry scheduler, второй ledger producer или независимое решение о final |
| Tools | `agent/tool_executor.py`, inline executors, `model_tools.py`, `tools/registry.py`, tool-specific approval | Прямой handler call в обход validation, hooks, approval и result persistence |
| Providers | `hermes_cli/runtime_provider.py`, client lifecycle, `agent/chat_completion_helpers.py`, `agent/auxiliary_client.py`, credential sources/pools | Новую таблицу precedence, смену ключа/endpoint или дополнительную fallback loop |

Конкретное уточнение ownership: `SessionDB.close()` для registry-managed объекта вызывает `release(self)`, то есть освобождает одну ссылку. Физическое закрытие выполняется на последнем release вне registry lock. Начальный docstring `hermes_state_registry.py` о no-op устарел; будущий адаптер не должен вызывать одновременно `close()` и `release()` для одного acquire.

Существующий runtime остаётся источником истины. Обёртка порта сначала переводит данные и делегирует прежнему владельцу. Перенос политики в application service — отдельный этап после доказательства совместимости.

## 2. Adapter Principles

1. Один владелец каждого эффекта: один durable write, один tool dispatch, одна transport send и одна recovery policy. Сравнение двух реализаций допустимо на изолированных fixtures; production shadow execution эффектов запрещено.
2. Адаптеры зависят от domain/ports и существующей инфраструктуры. Domain зависит от стандартной библиотеки; application зависит от domain и ports. Infrastructure реализует порты. Схемы прежних документов с последней стрелкой «domain → infrastructure» следует понимать как последовательность исполнения, а не разрешение Python-import из domain в инфраструктуру.
3. Profile, source/platform, caller authorization, session/turn/task identity и ownership lifetime передаются явно от доверенной composition boundary. Нельзя восстанавливать права по одному session ID или process environment.
4. Адаптер не загружает конфиг/секреты при импорте, не регистрирует себя в старом runtime и не запускает фоновые потоки. Будущий composition root передаёт ему конкретного владельца и правила освобождения ресурсов.
5. При невозможности выразить прежнюю гарантию текущим портом фиксируется contract gap. Нельзя добавлять динамические поля, прятать секреты в `options`, заводить глобальные side maps или незаметно ослаблять гарантии.
6. Ошибки lookup, contention, lost lease, replaced DB, отказ пользователя, provider failure и неопределённый ACK остаются различимыми. Общая конверсия всех исключений в False недопустима.
7. Совместимость — ограниченный перевод данных и вызов существующего механизма, а не новый внутренний re-export shim или универсальный manager.

По `SECURITY.md`, adapters и Protocol не создают security sandbox. Approval, tool grant и redaction — in-process меры; containment требует соответствующей OS isolation. Внешняя авторизация защищает dispatch, approval response и output на каждой поверхности.

## 3. Persistence Adapter

### Mapping и ownership

Предлагаемый persistence adapter предоставляет `PersistencePort.sessions` через отдельный `SessionRepository`, делегирующий профильному SessionDB. Он не владеет DDL, WAL или recovery implementation.

| Port operation / данные | Существующий механизм | Обязательное условие |
|---|---|---|
| `create(Session)` | SessionDB creation | Явно заданы source/profile и политика конфликта ID; отсутствие случайного upsert |
| `get(SessionId)` | SessionDB lookup | Detached domain projection; возвращаемый объект не является live SQLite row/connection |
| `get_by_key(SessionKey)` | SessionStore routing lookup, затем owning session DB | Routing home и transcript profile различаются; compression tip разрешается существующим владельцем |
| `save(Session)` | Разрешённые SessionDB mutations | Нельзя целиком перезаписать runtime row урезанной dataclass-проекцией |
| `list_active()` | Существующий session listing/filter | Понятие active согласовано: ended/archive/expiry и lease — разные признаки |
| Generation fields | Session/lease contract и runtime fencing | Не считать DB-file generation, turn run-generation и core counters одним числом |

Core Session не содержит всю runtime row: нет полного source/profile/origin, expiry, transcript и usage. Поля, отсутствующие в проекции, сохраняются прежним владельцем. `metadata: dict[str, str]` не служит неограниченным сериализованным контейнером runtime.

Адаптер может либо заимствовать handle у доверенного владельца без права закрытия, либо выполнить собственный registry acquire и ровно один release. Политика фиксируется при создании, включая failure paths. Не создавать bare SessionDB на каждый вызов при уже существующем shared owner.

### Transaction и generation rules

Mutation допускается только с проверкой актуального durable owner/token и ожидаемой версии в одной транзакционной операции существующего storage owner. Python `get → acquire_lease → save` не атомарен: два загруженных объекта могут оба получить lease. Текущий `SessionRepository.save(session)` не выражает expected version/CAS, а SessionService мутирует объект до save. Это блокер подключения записывающего adapter, а не задача, решаемая локальным Lock вокруг save.

Нужно отдельно согласовать контракт atomic acquire/release/close, lost-lease outcome и восстановление object state при persistence failure. До этого возможна только read projection. После ошибки нельзя сообщать successful ownership или продолжать tool side effects. Для нескольких процессов доказательство должно опираться на существующее durable fencing, не на GIL.

Транзакция не удерживается во время inference, approvals или network send. Lock retries и jitter наследуются от существующего storage API; второй retry loop не добавляется. Transcript flush, lease fence и compression reroute сохраняют их нынешнюю очередность. Одновременная запись transcript агентом и адаптером запрещена.

### WAL, migrations и recovery

Adapter не вызывает PRAGMA самостоятельно. WAL/DELETE compatibility, required-WAL refusal, checkpoint и DB replacement guards остаются в существующих владельцах. После замены файла старый handle освобождается в своё registry generation; путь к файлу не даёт права писать в новое поколение со старым состоянием.

Схема не меняется ради соответствия dataclass. Не выдумывать durable storage для core counters, пока не согласовано их отображение на существующую модель. Любая будущая schema migration потребует отдельного запроса и backward/restore proof.

Главные риски: потеря неотображённых полей, нарушение profile isolation, двойной release, stale write после compression, fallback в JSONL без корректного статуса caller. Validation: G1/G2 и C1 из regression execution plan; real temp DB, concurrent handles/processes, replacement и повторное открытие.

## 4. Delivery Adapter

### Transport и ledger

`DeliveryPort.send/edit` сейчас принимает Delivery с obligation ID, session key, content и локальным state. В нём нет platform/chat/thread/profile, message ID для edit, principal или recovery mode. Будущий transport adapter должен получать проверенный destination context от прежнего gateway owner; эти поля нельзя угадывать по строке session key. Ledger orchestration пока остаётся в gateway.

| Событие | Авторитетное решение | Mapping в core |
|---|---|---|
| Ответ подготовлен | Текущий producer записывает pending до send | Один obligation ID; core не создаёт параллельную строку |
| Отправка начата | attempting перед transport await | Локальный state не заменяет durable запись |
| Transport подтвердил успех | Только успешный SendResult даёт delivered | `DeliveryResult(success=True, external_id=...)` |
| Определённый отказ | failed с исходной классификацией | `success=False`, error; retryable лишь по прежней policy |
| Timeout/connection loss после возможного accept | Результат неоднозначен | Нельзя объявлять definitive reject только из факта исключения |
| Edit final | Прежний consumer/adapter использует правильный message ID | Не превращать отсутствие ID в скрытый второй send |

Ledger сейчас best-effort: его ошибка не должна сама блокировать send. Адаптер сохраняет этот контракт и наблюдаемую ошибку, не вводит новое обещание transactional outbox/гарантированной доставки. Строгое требование «нет durable pending — нет send» изменило бы поведение и требует отдельного решения.

### Retry, duplicate prevention и crash recovery

Retry остаётся у текущего gateway recovery: pending не начал send; attempting может уже находиться на платформе и восстанавливается с видимым marker; failed обрабатывается по действующим restart/reconnect правилам; delivered не отправляется повторно. Сохраняются owner PID/start time, profile routing, attempt cap и stale/abandoned policy. Retryable boolean не заменяет эту классификацию и не разрешает адаптеру повторять send самостоятельно.

Prefix-stable stream, interim marker, final consumer declaration и reconciliation через edit сохраняются. Exactly-once через неоднозначный remote ACK не обещается. Тестовый shadow adapter получает записанные outcomes или изолированный fake transport; повторять реальную отправку для сравнения нельзя.

### Блокеры текущего core

DeliveryService переводит любое transport exception в FAILED и возвращает лишь DeliveryState, теряя external_id/retryable/error для caller. В четырёх core states нет runtime abandoned, а DeliveryResult не различает unknown ACK и definitive failure. Необходимо согласовать result/error contract и сохранить metadata до интеграции; новый слой не должен становиться ledger owner с текущей семантикой. Async gateway transport и синхронный порт также требуют явного scheduling contract: никакого вложенного `asyncio.run` на активном loop.

Validation: G4/C2; crash windows pending/attempting/ACK, profile isolation, reconnect classification, edit/stream parity и ошибка ledger. Существующие profile tests переиспользуются, а не объявляются отсутствующими.

## 5. Tool Adapter

Будущий ToolExecutorPort adapter делегирует целому существующему execution path в agent, сохраняя inline-tool interception и middleware/registry dispatch. Прямой `registry.dispatch` для всех вызовов обошёл бы часть семантики.

| Контекст/этап | Граница |
|---|---|
| `session_id`, `turn_id`, `tool_call_id` | Те же identity на approval, pre/post hooks, persistence и result pairing |
| `capability_grant` | Ссылка на доверенную session-scoped политику, а не произвольная строка от модели |
| `approved` | Не разрешение отключить все проверки; approval должен относиться к конкретному действию и текущему owner |
| Profile/task/CWD/platform | Явный trusted runtime context; task ID не заменяется session ID |
| Thread workers | Существующая propagation ContextVars и callbacks сохраняется до завершения worker |
| Tool search / inline tools | Bridge раскрывается до реального tool identity; memory/todo сохраняют agent-specific owner |
| Hooks/results | Single-fire middleware и hooks, budgets, spill storage, incremental flush и result ordering остаются у прежнего executor |

Текущий ToolExecutionContext не содержит всех task/profile/cancellation/deadline полей. Их будущий источник фиксируется при composition для конкретного хода; нельзя брать process-global fallback. Frozen dataclass защищает запись полей, но не авторизацию и не mutability переданного Mapping arguments.

ExecutionService сейчас проверяет только непустое имя и вызывает port даже при approved=False. Поэтому нужно явно определить, кто проводит capability/approval enforcement и как передаётся отказ. До этого адаптер не имеет права интерпретировать boolean как bypass, вызывать subprocess сам или продолжать после stale/cancelled turn.

`check_fn` означает reachability/opt-in, а surface tool grants зависят от сессии. Сохраняются terminal/file/ACP checks и выбранный backend. Terminal sandbox не ограничивает автоматически MCP, plugin или host code execution; архитектурный слой не меняет trust model.

Validation: G5/C3, sequential/concurrent/segmented и inline paths, denied/timeout/interrupted approvals, grant isolation, late worker completion, hook single-fire и oversized results. При shadow comparison сравниваются records, а effect исполняет ровно один owner.

## 6. Provider Adapter

Предлагаемый ProviderPort adapter переводит запрос в существующий resolver, затем проецирует route metadata. Он не заводит собственный provider catalog, precedence или recovery algorithm. Main и auxiliary purpose направляются в соответствующие существующие механизмы; одинаковый provider name не означает одинаковую policy.

### Routing ownership

`resolve_runtime_provider` сохраняет lazy ladder: disabled guard, requested shortcuts, custom/local alias, local endpoint bypass, auth/explicit route, pool, OAuth/native/external и заключительный fallback. Не вычислять все кандидаты заранее: resolution может обновить auth/pool state. «Только metadata» не гарантирует отсутствие побочных эффектов resolver, поэтому production shadow повторный resolve без отдельного исследования запрещён.

ProviderRouter остаётся forwarding boundary. Модель, endpoint, API mode и credential reference образуют одну согласованную проекцию. Auxiliary task overrides/main inheritance/discovery сохраняются в auxiliary resolver. Main fallback, retry budget, unavailable entries и credential rotation остаются у нынешних owners до отдельно проверенной передачи ответственности.

### Credentials и совместимость

CredentialReference — opaque ссылка, привязанная к profile и credential source. Raw key/token не попадает в RouteDecision, `options`, repr, сериализацию или логи. Доверенный infrastructure owner разрешает reference при client creation и сохраняет OAuth refresh/pool scope. Reference нельзя трактовать как произвольный путь или имя environment variable от caller.

Сейчас порт не определяет profile scope и lifecycle reference, а RouteDecision использует `route_purpose`, хотя hardening specification называла `purpose`. Это требует contract agreement перед mapping; не добавлять скрытые aliases в адаптер. Существующие API mode strings и endpoint normalization проверяются differential matrix, а не меняются при переводе.

RuntimeApplication сейчас захватывает lease перед route без cleanup при route exception. Provider adapter не должен освобождать чужой session lease: это задача future application orchestration, которая блокирует live integration до отдельного исправления. Prompt identity rewrite при fallback также требует принятой cache policy; adapter не мутирует prompt/history.

Validation: G6/C4, explicit/custom/local/pool/OAuth/native paths, два профиля, exhausted fallback, purpose propagation, фиктивный secret sentinel и failure cleanup. Network/OAuth calls заменяются на внешней границе для deterministic tests; реальные SDK/сервисные smoke checks — отдельный gate, не скрытый prerequisite анализа.

## 7. Migration Sequence

Порядок ниже является предложением будущих задач. Все шаги сохраняют существующие owners до явно согласованной передачи; готовность контрактов имеет приоритет над календарным порядком.

| Шаг | Owner before | Owner after | Compatibility layer | Rollback strategy | Validation gate |
|---|---|---|---|---|---|
| 1. Зафиксировать baseline и закрыть contract gaps | Нынешние runtime owners | Те же owners | Только согласование типов, scope и observable semantics | Отменить только новый contract slice; никакого data rollback | G1–G7 применимых областей; naming, unknown ACK, atomic lease и cleanup decisions |
| 2. Read-only persistence projection в изолированном consumer | SessionDB + SessionStore | Они же; adapter читает | Detached Session projection с явным profile/routing home | Отключить consumer, release только своих handles | G1/G2; сохранение полей, no writes, close/refcount |
| 3. Provider mapping без переноса fallback | Старые main/auxiliary resolvers | Они же за ProviderPort | Purpose-aware projection и opaque credential reference | Вернуть прежний вызов resolver; не откатывать секреты/auth storage | G6/C4; precedence, pool effects и profile isolation |
| 4. Atomic session mutations для одного consumer | Прежние lease/SessionDB owners | Storage fencing остаётся; сервис координирует только согласованные команды | Existing transactional API с согласованной expected-version semantics | Drain consumer, освободить его leases, вернуть прежний call path | G1/G2/C1; два процесса, stale writer и save failure |
| 5. Delivery transport mapping | Gateway ledger/recovery + transport | Те же; DeliveryPort получает transport outcome | Destination-bound transport/result translation, без второго ledger | Stop new sends, завершить/зафиксировать attempts, вернуть старый sender | G4/C2; ACK/crash/markers/edit и ledger failure |
| 6. Tool mapping для одного turn consumer | Agent executor + approvals/hooks | Те же за ToolExecutorPort | Полный trusted turn context и прежняя pipeline | Drain tools/approvals, вернуть прежний dispatcher; выполненные эффекты не повторять | G5/C3; parity paths, denied/interrupted, single-fire |
| 7. Перенос одной application workflow после предыдущих gates | Surface orchestration | RuntimeApplication координирует одну выбранную поверхность; инфраструктурные owners сохранены | Composition wiring без дублирующего execution | Quiesce workflow и вернуть прежний controller на том же формате состояния | G1–G7, G3 lifecycle, restore/rollback receipt и applicable evals |

Адаптеры не требуют предварительного массового перемещения файлов. Перенос retry, delivery ledger или DB lifecycle ownership не входит автоматически в шаг подключения порта: это отдельный migration slice. Не начинать одновременно с замены всех CLI/TUI/gateway/cron consumers.

## 8. Rollback Strategy

До каждого будущего шага фиксируются baseline SHA, изменённый consumer, профиль, ownership handles/leases, формат данных и receipts. Обратимый rollout сохраняет прежнюю схему и текущие пути авторитетного storage; новый cache не становится единственной копией состояния.

При откате сначала остановить intake выбранного consumer, затем дождаться или корректно прервать его workers, approvals и sends. Не закрывать чужой SessionDB или весь registry, не освобождать чужие leases, не выполнять повторно tools. Не использовать recursive process kill по имени; соблюдать существующие shutdown/drain и OS-specific ownership rules.

После возврата старого call path проверить resume и routing, generation fencing, provider identity, DB health и unresolved delivery obligations. Сохранять original ledger: unknown ACK нельзя превратить в delivered вручную ради чистого rollback. Повторная доставка идёт через прежнюю recovery policy с marker и limits.

Если требуется восстановление данных, сначала quiesce writers и использовать поддерживаемый согласованный backup/restore. Не удалять live WAL/SHM, не копировать произвольно активную тройку файлов, не понижать schema и не откатывать credential rotation. Для этого дизайна schema change вообще не требуется.

Rollback считается подтверждённым только по отдельному receipt: прежняя версия запускается, известная session восстанавливается, owning handles/leases корректны, obligations не потеряны и профиль не сменился. Неисполненные проверки остаются UNVERIFIED.

## 9. Validation Gates

| Gate | Что должно быть доказано перед integration |
|---|---|
| Domain/application | C1–C4 из [regression execution](regression-harness-execution.md): реальное поведение core, а не только import success; route exception не оставляет lease |
| Port compatibility | Типы/signatures и реальные вызовы согласованы; missing context/outcome не скрыт в `object`/metadata; adapters не импортируются core |
| Persistence | Temp profile, реальные SessionDB/imports, concurrent owners, WAL fallback, migration/reopen, generation replacement и recovery; один release на acquire |
| Delivery | Exact profile/destination, pending/attempting/ACK/crash, best-effort ledger policy, transient/permanent distinction, stream final/edit |
| Tools/security | Trusted identity/grant, enforcement owner, existing hooks/approval/backend isolation; пользовательские session IDs не дают прав |
| Providers | Lazy precedence, full route coherence, credentials scoped и не сериализованы, main/auxiliary/fallback distinction |
| Lifecycle/platform | Intake/drain всех agent/cron/API/deferred classes, native OS tests при process changes, rollback receipt |
| Harness | `scripts/run_tests.sh` с подходящими G1–G7; real imports и temp HERMES_HOME; snapshots формы source запрещены |
| Evals | Paired pinned trees для применимых navigability, fanout, compaction/tool/browser tests; infrastructure failures отдельно от scores |

Проверки выполняются в будущих implementation-задачах, не в этом analysis sprint. Каждый receipt хранит SHA, ОС/Python/SQLite, command/selector, executed/skipped count, failures/retries и границы доказательства. Flaky или непроверенная P0-граница блокирует относящуюся к ней миграцию. Политика назначения tools и stable prompt/cache сохраняется согласно `AGENTS.md`.

## Acceptance Criteria

- Создан только этот архитектурный документ; файлы в `.ai/` не создавались и не изменялись.
- Production runtime, `hermes_core`, тесты, schema и workflows сохранены.
- Для каждого адаптера указаны прежний owner, mapping, scope и ограничения текущего порта.
- Последовательность миграции включает compatibility layer, rollback и regression gate на каждом шаге.
- Существующий runtime остаётся авторитетным; готовность реализации не объявлена на основании статического анализа.
