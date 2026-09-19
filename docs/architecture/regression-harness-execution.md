# Sprint 1.4.2 — стратегия выполнения regression harness

Дата: 2026-09-19. HEAD при анализе: `e2428d92a90b9b788c7a86f7cc7fdb9327199a75`.

Режим: только анализ и документация. Имя результата задано текущим запросом: этот файл дополняет, а не заменяет `regression-harness-plan.md`. Тесты, evals, приложение и import/compile checks в этой задаче не запускались. Название execution означает план будущего выполнения; результатов PASS для runtime здесь нет.

Прочитаны задание Sprint 1.4.2, `AGENTS.md`, `SECURITY.md`, архитектурные документы, новый `hermes_core`, runner и выбранные тесты. Наличие теста и прочитанная assertion подтверждают существование защиты, но не её успешное выполнение. Исследование выборочное: «не подтверждено» не означает «во всём репозитории отсутствует».

Исходное состояние дерева: уже изменён `.ai/prompts/sprint-1.4.2-regression-harness.md`. Этот пользовательский Markdown сохранён. Единственная запись этой задачи — `docs/architecture/regression-harness-execution.md`.

## 1. Current Test Landscape

| Источник | Что установлено чтением | Граница доказательства |
|---|---|---|
| `scripts/run_tests.sh` | Выбор Python с pytest, чистое окружение, UTC/UTF-8/hash seed, передача файлов в parallel runner; есть Windows Scripts-layout | Runner не запускался; доступность среды не проверена |
| `scripts/run_tests_parallel.py` | Изоляция subprocess на файл, bounded parallelism, timeout и один повтор упавшего файла; отсутствие выполненных тестов отслеживается | Успех после retry — flaky, даже если exit code зелёный |
| `tests/conftest.py` | `_isolate_hermes_home`, live-system guards, host OS markers | Для profile paths дополнительно нужен временный `Path.home()`; subprocess также должен получить изолированный профиль |
| `tests/state/`, `tests/hermes_state/` | Реальные SQLite-тесты leases, lineage, registry generations и contention | Не каждый тест является multi-process или crash test |
| `tests/gateway/` | Lifecycle, drain, ledger, streaming и authorization; реальные компоненты часто соединены с fake transport/agent | Транспортный stub не доказывает поведение удалённой платформы |
| `tests/tui_gateway/` | В частности, resume ownership проверяется `_RecordingDB`, считающим close | Это проверка передачи владения, а не SQLite/WAL интеграция |
| `tests/tools/`, `tests/run_agent/`, `tests/hermes_cli/` | Registry dispatch, propagation, approvals, resolution и fallback | У каждого сценария нужно проверить глубину mocks перед утверждением E2E |
| `hermes_core/` | Domain values, Protocol-порты, небольшие сервисы; инфраструктурные адаптеры отсутствуют | По поиску `rg -n 'hermes_core' tests` прямые ссылки в тестах не найдены; runtime suite не доказывает контракт нового слоя |

Прежние планы используются как перечень рисков, а не как актуальный coverage report. Например, `test_delivery_ledger.py` уже содержит `test_profile_scope_never_claims_another_bot_identity` и `test_runtime_profile_redelivery_uses_matching_bot_adapter`: объявлять profile recovery полностью непокрытым неверно. Также текущий `test_shared_session_db_registry.py` содержит `test_close_on_shared_instance_releases_one_refcount`; старое утверждение аудита о безусловном no-op `close()` нельзя использовать как oracle без сверки текущей реализации.

Правила `AGENTS.md`: Python-тесты только через канонический runner; никаких source-text assertions, snapshots каталога/числа версий, подмены ОС через `sys.platform`. Тесты проверяют отношения данных и реальные границы. Системный prompt и история требуют сохранения cache/role contracts. По `SECURITY.md`, approval и capability grant — не sandbox: containment против adversarial LLM обеспечивает ОС. Session ID сам по себе не авторизует запрос, выдачу output или approval.

## 2. Golden Test Suite Definition

Golden suite — версионируемый перечень поведенческих проверок до/после выбранного изменения. Он не означает эталонный дамп БД или побайтовый snapshot всего ответа модели. Минимум выбирается по затронутым границам; при замене общей orchestration обязательны все блоки G1–G6 и будущий G7.

| Блок | Существующие файлы для первого запуска | Обязательный результат |
|---|---|---|
| G1 Session | `tests/state/test_session_turn_lease.py`; `tests/state/test_compression_lineage_guard.py`; `tests/tui_gateway/test_session_resume_db_ownership.py`; `tests/gateway/test_session_store_expiry_finalized.py` | Owner fencing, lineage ambiguity fails closed, корректная передача/освобождение handle, сохранение причины reset |
| G2 Storage | `tests/hermes_state/test_shared_session_db_registry.py`; `tests/hermes_state/test_deleted_wal_generation_guard.py`; `tests/state/test_state_db_wal_unlink_race.py`; `tests/test_hermes_state_wal_fallback.py`; `tests/state/test_dedupe_migration_contention.py` | Generation isolation, journal policy, конкурентные open/migration и отказ от stale writes |
| G3 Lifecycle | `tests/gateway/test_startup_restart_race.py`; `tests/gateway/test_shutdown_executor_quiesce.py`; `tests/gateway/test_cron_active_work_drain.py`; `tests/gateway/test_api_server_active_work_drain.py`; `tests/gateway/test_hygiene_deferred_work_drain.py` | Intake/restore не гоняются с restart; каждая категория работы видна до реального завершения |
| G4 Delivery | `tests/gateway/test_delivery_ledger.py`; `tests/gateway/test_restart_drain_recovery_dedup.py`; `tests/gateway/test_stream_final_contract.py` | Claim scoped по owner/profile; неоднозначная отправка помечена; final не дублируется обычным send |
| G5 Tools | `tests/tools/test_registry.py`; `tests/run_agent/test_tool_executor_contextvar_propagation.py`; `tests/tools/test_approval_mode_parity.py`; `tests/tools/test_approval_interrupt.py` | Dispatch, availability и propagation корректны; approval mode/interrupt сохраняются |
| G6 Routing | `tests/hermes_cli/test_runtime_provider_resolution.py`; `tests/hermes_cli/test_runtime_provider_late_binding.py`; `tests/run_agent/test_provider_fallback.py`; `tests/run_agent/test_fallback_credential_isolation.py`; `tests/run_agent/test_fallback_api_mode_preservation.py` | Порядок выбора, привязка ключа к endpoint/provider и API mode сохраняются |
| G7 Core | Пока нет подтверждённого отдельного набора; сценарии разделов 7–8 | Только после отдельной реализации и запуска; существующий runtime нельзя подменять для «зелёного» результата |

Golden storage fixtures должны быть синтетическими: свежая БД, поддерживаемая старая схема с известными сообщениями, compression parent/child, две profile DB, ledger с известным ACK state. Проверять сохранность сообщений, связей, usage и obligations, идемпотентность повторного открытия, достижение текущего schema contract и целостность БД после завершённого восстановления. Не фиксировать номер схемы или размер WAL как вечную константу. Согласованные backup/restore делать через поддерживаемый механизм; последовательное копирование живых DB/WAL/SHM само по себе согласованность не гарантирует.

## 3. Critical Regression Matrix

### R1 — создание, resume, close и expiry

Behavior: начало сессии, передача DB handle живому агенту, ранний отказ resume, финализация и expiry без потери предыдущей причины reset.

Current protection: surface lifecycle handlers и durable session store; `_RecordingDB`-тесты отдельно проверяют ownership handoff.

Existing tests: `tests/tui_gateway/test_session_resume_db_ownership.py`, `tests/tui_gateway/test_finalize_session_persist.py`, `tests/gateway/test_session_store_expiry_finalized.py` (`test_promotes_live_row`, `test_does_not_overwrite_existing_session_reset`).

Missing tests: в исследованной выборке не подтверждён единый real-DB RPC create → resume → close с arrival на границе expiry. Сначала найти расширение существующего теста, затем планировать новый.

Risk: преждевременное закрытие shared handle, потерянный transcript, неверная граница разговора.

Priority: P0 при миграции SessionService.

### R2 — concurrency, rotation и compression lineage

Behavior: два владельца, stale release/flush, смена compression tip; fork/delegate не должны ошибочно блокировать родителя.

Current protection: durable turn lease, owner fencing, обход lineage и отказ при неоднозначном child.

Existing tests: `tests/state/test_session_turn_lease.py` (`test_turn_lease_refresh_and_release_are_owner_fenced`, `test_turn_lease_fences_stale_transcript_flush_after_reclaim`), `tests/state/test_compression_lineage_guard.py`, `tests/agent/test_session_rotation_flush_cold_resume_68454.py`.

Missing tests: не подтверждён сравнительный сценарий старого runtime и нового repository adapter с двумя независимо загруженными объектами одной сессии.

Risk: два успешных владельца, потеря flush или запись в завершённого parent.

Priority: P0.

### R3 — SQLite, WAL, migrations, registry и recovery

Behavior: contention, retirement поколения после замены файла, ошибки cold open, journal fallback и восстановление без потери данных.

Current protection: shared registry и специализированные DB guards; миграции тестируются отдельно от application services.

Existing tests: G2; registry включает `test_concurrent_cold_acquire_opens_one_writer`, `test_open_failure_after_replacement_leaves_no_stale_entry`, `test_final_release_does_not_hold_registry_lock_during_close`; recovery дополнен `tests/gateway/test_session_db_corrupt_fallback.py` и `tests/gateway/test_session_db_replaced_fallback.py`.

Missing tests: не подтверждён сквозной receipt migration → active writer → остановка → supported restore → reopening с сопоставлением сообщений/ledger. Не смешивать в одном тесте все произвольные отказные комбинации.

Risk: повреждение поколения WAL, leaked handle, потеря данных при rollback.

Priority: P0.

### R4 — startup, shutdown, restart, workers, cron, API и deferred work

Behavior: входящие сообщения во время restore; stop во время startup; drain считает все категории работ; worker остаётся активным после coroutine timeout.

Current protection: startup gate, shared stop task, counters и watchdog.

Existing tests: G3; `test_hygiene_deferred_work_drain.py` содержит реальный блокирующий thread с Events и проверки deferred accounting; `tests/gateway/test_shutdown_watchdog.py` и `tests/gateway/test_startup_watchdog.py` дополняют таймауты.

Missing tests: совместное завершение всех четырёх категорий в одном изолированном процессе с повторным стартом; точная process topology desktop restart на каждой ОС требует отдельного receipt.

Risk: сиротские workers, premature DB close, остановка чужого процесса.

Priority: P0.

### R5 — delivery ledger, retry, crash и streaming final

Behavior: pending/attempting/failed/delivered, claim после смерти owner, transient reconnect и definitive rejection, final edit.

Current protection: ledger с owner/profile scope и ACK semantics; stream contract.

Existing tests: G4; `test_delivery_ledger.py` проверяет marker после attempting, permanent failure, profile identity и очистку resume до send. `test_stream_final_contract.py` проверяет interim sends и edit queued response.

Missing tests: реальное завершение subprocess в контролируемых точках до send, после remote accept до local ACK и после durable ACK; текущие staged-row/fake-transport тесты не заменяют этот эксперимент.

Risk: потеря сообщения или неотмеченный дубль. Exactly-once в неоднозначном сетевом окне не заявляется.

Priority: P0.

### R6 — registry, approvals, capability, hooks и concurrent execution

Behavior: registered handler вызывается через dispatch; capability scoped к сессии; callbacks переносят контекст; отменённый batch не начинает поздний side effect.

Current protection: registry, executor gates и tool-specific approvals. Доступность schema не равна authorization.

Existing tests: G5; registry содержит `test_register_and_dispatch`, discovery и concurrent register/deregister checks. Дополнительные наборы: `tests/tools/test_approval_plugin_hooks.py`, `tests/tools/test_approval_hook_session_id.py`, `tests/test_transform_tool_result_hook.py`.

Missing tests: parity одного семантического вызова в inline/sequential/concurrent/segmented путях с проверкой single-fire hooks и result pairing; полнота existing executor coverage требует отдельной инвентаризации до добавления теста.

Risk: approval привязан к чужому вызову, двойной hook, позднее исполнение.

Priority: P0 при изменении execution, P1 иначе.

### R7 — provider/model resolution, credentials и fallback

Behavior: explicit overrides, local/custom endpoint, pool, native API mode, fallback exhaustion и auxiliary inheritance.

Current protection: ordered lazy resolver и recovery paths действующего runtime.

Existing tests: G6; `tests/gateway/test_fallback_chain_reload.py`, `tests/run_agent/test_24996_fallback_exhaustion_cooldown.py`.

Missing tests: differential adapter matrix основной/auxiliary route и request bytes при fallback/resume. Конфликт byte-stable prompt policy и rewrite identity из аудита требует решения, а не закрепления произвольного нового ожидания.

Risk: смена endpoint с неправильным ключом, неверная precedence, бесконечный retry, cache regression.

Priority: P0 при routing migration.

## 4. Missing Coverage

Подтверждённый результат поиска: прямых ссылок на `hermes_core` в `tests/` не обнаружено. Поэтому import success из прошлой задачи не заменяет domain/service/port regression coverage.

Для прежнего runtime перечисленные в R1–R7 сквозные сценарии имеют статус «не подтверждено в выборке». Существующие focused tests сохраняются; новый сценарий нужен только если реальные assertions не покрывают нужную границу. В частности, profile delivery, stale turn writes и cold registry acquisition уже имеют конкретную защиту.

Открытые contract gaps нового слоя: атомарность acquire/save; освобождение lease при route exception; определённость владельца при пустом/некорректном owner; ACK ambiguity; propagation полного DeliveryResult; enforcement approval/capability; `purpose`/`route_purpose` naming. Эти вопросы блокируют соответствующую интеграцию, но не требуют изменения runtime в данном спринте.

## 5. Test Execution Strategy

Все команды ниже — план для отдельно разрешённого выполнения. В этой analysis-only задаче они не запускались.

1. Зафиксировать baseline/candidate SHA, diff, Python/SQLite/OS, dependency lock и версии fixtures. Выбрать применимые G-блоки и критерии до запуска.
2. На каждую сторону использовать отдельные временные profiles/workspaces. Real DB/imports обязательны для I/O/resolution; fake transport и фиктивные ключи допустимы на внешней границе. Production credentials и live profile не используются.
3. Запустить выбранные файлы каноническим runner. Пример G1:

```bash
scripts/run_tests.sh tests/state/test_session_turn_lease.py tests/state/test_compression_lineage_guard.py tests/tui_gateway/test_session_resume_db_ownership.py tests/gateway/test_session_store_expiry_finalized.py
```

4. Для точной диагностики использовать file path и `-k`, не полагаться на `file::node` как файловый selector. Нулевой collected/executed count — не PASS. Учитывать `--file-timeout`, `-j` и flake receipt; retries не скрывать.
5. После focused checks — соответствующий domain набор и требуемые CI gates. Windows-only checks — native Windows, Linux/macOS — свои маркированные lanes. Для venv/process ownership применить `wine2e` согласно root instructions. Synchronization через Events/barriers; wall-clock пределы не строить на предположении свободного runner.
6. В будущей contract-задаче импортировать каждый новый модуль в свежем процессе и проверить `get_type_hints` портов, доступность signature и отсутствие загрузки runtime/SDK. Компиляция/root import сами по себе не проверяют все модули или все потенциальные циклы. Не добавлять source-reading pytest.
7. Выполнить только релевантные evals по таблице ниже. Отчёты PASS/FAIL/SKIP/UNVERIFIED/FLAKY/INFRA_ERROR разделять; сборка среды или таймаут не является снижением качества модели.

| Eval | Когда нужен | Ограничения |
|---|---|---|
| `codebase_navigability` | Перенос модулей и изменение import graph | static/lookup offline; runtime_bench реально импортирует/исполняет дерево; проверить provenance |
| `fanout_resource_bench.py` | Worker/delegation lifecycle | Fake inference, реальные threads/processes/worktrees; сравнить RSS/FD/children после settle |
| `compaction` | Compression/context changes | Платные model calls, recall judging; синтетические или разрешённые обезличенные данные |
| `core_tool_deferral` | Tool exposure/bridge | Реальный агент, часть handlers stubbed; инфраструктурные exit отдельно от score |
| `session_search_schema` | Search schema changes | Минимальный loop; не доказывает весь AIAgent runtime |
| `readtool`, `browser_use` | File/browser execution changes | Live services; pinned arms, одинаковые задачи и повторения по README |

Receipt будущего запуска: блок/сценарий, точная команда, SHA, ОС/Python/SQLite, fixture/seed, executed/skipped count, exit code, первый сбой и retry, stdout/stderr без секретов, подтверждённая граница и невыполненные gates. Время/ресурсные пороги устанавливаются по baseline до сравнения; результат должен сохранять корректность, а не только улучшать размер файлов.

## 6. Migration Gates

| Gate | Условие принятия | Когда блокирует |
|---|---|---|
| Scope | Изменения соответствуют отдельной задаче; runtime остаётся authoritative до явной миграции | Необъявленное подключение core или изменение schema/API |
| Baseline | Применимые G1–G6 действительно выполнены на base/candidate | Известный failing baseline не переименован в regression кандидата, но обязательная проверка остаётся незакрытой |
| Core contracts | G7 реализован отдельно, сценарии 7–8 выполнены | Stale owner, route-failure lease, approval или result semantics не определены |
| Persistence | Real temp DB подтверждает atomic ownership и generation fencing | Простой get/mutate/save не доказывает CAS/транзакцию |
| Delivery | Сохранены ledger/ACK/retry/profile semantics | Ambiguous exception выдаётся за definitive reject или promised exactly-once |
| Routing/tools | Сохранены precedence, credential scope и context/hook ordering | In-process grant объявлен sandbox либо новый resolver обходит прежние правила |
| Platform/recovery | Native process tests и supported backup/restore/rollback receipt | Один mock lane выдаётся за доказательство всех ОС |
| Integration | Один concrete adapter и consumer за шаг; compare без duplicate side effects | Shadow-run повторно отправляет сообщения или исполняет tools |

Решение GO относится только к проверенной области. Сейчас выполнение runtime gates — UNVERIFIED; это документ стратегии, а не разрешение на замену runtime.

## 7. Hermes Core Contract Validation

Предлагаются три уровня будущего harness: domain methods на настоящих value objects; application services с recording/failing ports; затем differential tests конкретного infrastructure adapter против текущего runtime в временном профиле. Protocol-совместимость проверять type checker/signatures и реальными вызовами; обычный Protocol не обеспечивает runtime validation автоматически.

| Сервис/порт | Проверяемое наблюдение | Ограничение текущего кода |
|---|---|---|
| SessionService / SessionRepository | create сохраняет идентичность; missing resume даёт LookupError; успешные mutations сохраняются, stale rejection не вызывает save | save не принимает expected generation; rollback mutable object при save exception отсутствует; cross-process atomicity не определена |
| RuntimeApplication | id/key resolution, acquire → route, finish с lease generation; ошибка route освобождает владение по согласованному контракту | Сейчас acquire происходит до route без cleanup; execution/persistence/delivery не составляют полного run workflow |
| ExecutionService / ToolExecutorPort | Записать exact arguments и все поля контекста; пустое имя не вызывает executor; result/exception передаются | `approved=False` не предотвращает вызов порта, grant не проверяется; enforcement должен быть определён до адаптера |
| DeliveryService / DeliveryPort | Получает DeliveryResult; success и отказ дают разные состояния; exception имеет отдельную классификацию | Возвращает только DeliveryState, теряя external_id/retryable/error для caller; exception переводит obligation в failed |
| ProviderRouter / ProviderPort | Forward provider/model/purpose/options и immutable route; исключение не заменяется неявным fallback | Это делегирование resolve; собственного precedence/fallback алгоритма в core нет |

Нельзя присоединить SQLite, gateway или provider SDK к core только для прохождения теста. Реальные инфраструктурные адаптеры проверяются отдельно, используют существующую реализацию как oracle и не допускают двойного исполнения эффектов. Переход к новому owner требует договорённого fencing/transaction contract, сохранения credential reference и transport acknowledgment.

## 8. Hermes Core Contract Regression

### C1 — Session contract

Behavior: create, acquire, owner release, stale rejection, owner close, независимость счётчиков.

Current protection: mutable Session сравнивает owner и `lease_generation`; acquire увеличивает оба счётчика, release/close — только `generation`.

Existing tests: прямых core tests не найдено; runtime `test_session_turn_lease.py` не тестирует этот dataclass.

Missing tests: построить session с `(generation, lease_generation)=(0,0)`; acquire A → `(1,1)`; release A/1 → `(2,1)`; повторный acquire A → `(3,2)`; stale A/1 и другой owner не меняют поля; close A/2 → `(4,2)`, CLOSED и owner None. Отдельно duplicate acquire, acquire CLOSED, повторный release/close и отказ save. Проверить пустого owner и runtime-передачу None: type hints не запрещают её, а owner None на свободной сессии может совпасть с sentinel. Нужен явный контракт отказа. Два независимо загруженных объекта одной session id должны иметь одного durable владельца; текущий dataclass этого не гарантирует.

Risk: stale closure и false confidence в distributed lease. `RuntimePlan.generation` содержит lease token, а не session state version; проверить смысл, не только имя.

Priority: P0 до session adapter.

### C2 — Delivery contract

Behavior: immutable DeliveryResult, success/failure/retryable, допустимые переходы и неоднозначный transport failure.

Current protection: frozen result; pending → attempting увеличивает attempts; подтверждение/отказ доступны только из attempting.

Existing tests: direct core coverage не найдено; runtime ledger tests задают будущий semantic oracle.

Missing tests: FrozenInstanceError при записи result; premature ACK отклонён без mutation; send видит ATTEMPTING; success=True завершает DELIVERED, False — FAILED; retryable=True не вызывает скрытый retry; delivered повторно не отправляется. Проверить, как caller получает external_id/error/retryable — сейчас сервис их не возвращает. При accept-then-exception нельзя автоматически объявлять definitive failure: согласовать unknown/attempting semantics с ledger. Противоречивые result fields допускаются dataclass; определить, какие комбинации допустимы.

Risk: утрата retry/ACK metadata и скрытая повторная доставка при будущей интеграции.

Priority: P0 до delivery adapter.

### C3 — Tool execution contract

Behavior: создание frozen ToolExecutionContext; propagation session/turn/call/grant/approved; approval boundary.

Current protection: frozen dataclass и forward в executor; проверяется только непустое имя инструмента.

Existing tests: direct core coverage не найдено; contextvar и approval runtime tests относятся к прежнему executor.

Missing tests: неизменяемость каждого поля и точная передача recording port; grant не меняется между двумя session contexts; result/exception возвращены без подмены. Характеризовать текущий вызов при approved=False отдельно от будущего требования запретить side effect без разрешения. Перед адаптацией определить enforcement owner, обязательность turn/call IDs и поведение missing grant. Frozen context не делает arguments Mapping immutable.

Risk: контекст выглядит авторизованным контрактом, хотя enforcement отсутствует. OS boundary от этого не появляется.

Priority: P0 до tool adapter.

### C4 — Routing contract

Behavior: frozen RouteDecision, provider precedence и credential reference isolation.

Current protection: route immutable; router делегирует ProviderPort.resolve. Фактическое поле dataclass — `route_purpose`, тогда как hardening prompt требует `purpose`; порт принимает `purpose`.

Existing tests: direct core coverage не найдено; G6 проверяет прежний resolver.

Missing tests: immutable fields; exact forward явно выбранной модели/provider/options/purpose; route строится без secrets/SDK clients; две profile references не смешиваются. Перед реализацией адаптера согласовать naming `purpose` и проверить построение/сериализацию контракта. Precedence проверять на реальном resolver через adapter, а не на fake ProviderPort, возвращающем заранее выбранный ответ. Frozen string `credential_reference` сам по себе не мешает записать в него raw secret: запрет доказывается mapping-тестом с фиктивным secret sentinel.

Risk: несовместимость keyword construction, credential leak и недоказанная routing parity.

Priority: P0 до provider adapter.

Итог scope: создаётся только этот документ. Предыдущие архитектурные документы, пользовательский prompt, `hermes_core`, production runtime и тесты сохранены. Финальная проверка включает `git diff --name-only` и `git status --short`, поскольку новый untracked Markdown не виден в обычном diff.
