# План защиты поведенческого baseline Hermes

Дата: 2026-09-19. Проверяемая ревизия: `d05d19a94be20ef04e31e8f7e3f64264494b8a35`.

Документ подготовлен в режиме analysis only по заданию `.ai/prompts/sprint-1.4.1-baseline-protection.md`. Он описывает, что нужно проверить перед будущей реструктуризацией runtime. Production-код, API, схема БД и тесты этим заданием не изменяются. План не утверждает, что перечисленные проверки уже выполнены.

Основа анализа: [runtime-audit.md](runtime-audit.md), [AGENTS.md](../../AGENTS.md), [SECURITY.md](../../SECURITY.md), area-инструкции в `gateway/`, `agent/`, `tools/`, `tui_gateway/`, `hermes_cli/`, а также README и harness-описания в `evals/`. Для запуска Python-проверок проект требует `scripts/run_tests.sh`, временный `HERMES_HOME` и реальные импорты на границах persistence, routing, security и I/O.

## 1. Current Behavior Map

### Сессия

Событие транспорта превращается в `MessageEvent` с `SessionSource`. Ключ маршрутизации учитывает платформу, чат, thread/topic и профиль. `SessionStore` владеет индексом активного маршрута, а `SessionDB` — строками сессий, сообщениями, usage и конфигурацией модели. Это разные владельцы: routing index нельзя записывать в БД случайно выбранного multiplex-профиля.

При создании или начале хода gateway резервирует active-session lease. `SessionState` делит память на `TurnState`, `ConversationState` и `PersistentState`; очистка хода не должна стирать настройки разговора, а граница `/new`, reset, expiry или resume не должна сбрасывать монотонный `run_generation`. TUI `session.resume` может переиспользовать живой runtime либо восстановить холодный агент. Восстановление истории не возобновляет старый Python-поток.

Закрытие сессии, завершение durable row, release lease, archive и delete — различные операции. Конкурирующий runtime должен быть проверен перед финализацией. Compression создаёт lineage и может менять активный session id через compression tip.

### Persistence и SQLite/WAL

`hermes_state.py` собирает schema, messages, FTS, usage, compression, gateway и repair mixins. `hermes_state_dbfile.py` проверяет application id, нулевой/заменённый файл и поколения sidecar-файлов. `hermes_state_registry.py` обеспечивает один shared `SessionDB` на путь в рамках процесса, refcount и retirement старого поколения при замене inode.

Обычный режим — WAL с общей памятью и блокировками; на несовместимом filesystem разрешён контролируемый fallback в DELETE, а при `require_wal=True` ожидается отказ. WAL ограничивается по размеру. Удалённое поколение `-wal`/`-shm` не должно позволять второму процессу создать новую несовместимую генерацию. Header probes не должны закрывать fd, удерживающий POSIX SQLite lock.

Миграции и декларативное добавление колонок должны быть идемпотентны. Фактический `SCHEMA_VERSION` берётся из `hermes_state_common.py`; старые guides могут отставать и не являются oracle.

### Gateway и workers

Gateway startup: runtime lock/PID, policy/access checks, recovery прошлого запуска, inbound restore gate, warm-up turn machinery, подключения платформ и профилей, redelivery obligations, runtime status, background watchers. Входящие сообщения во время restore ставятся в очередь и выпускаются после bounded gate; timed-out restore продолжает работу в фоне с уже занятыми слотами.

Shutdown имеет отдельные этапы drain, interrupt, tool-process cleanup, adapter finalization, session DB quiesce и exit-state persistence. В active-work aggregate входят messaging agents, cron, API-server runs и deferred executor workers. Одной карты `_running_agents` недостаточно.

Desktop `serve`, dashboard и messaging gateway имеют разные process-lifetime правила. Detached action, explicit terminate, gateway restart watcher и OS-specific process flags должны проверяться фактически на Windows и POSIX.

### Delivery recovery

Перед отправкой final response ledger должен записать `pending`; непосредственно перед await — `attempting`; только успешный `SendResult` переводит строку в `delivered`; definitive rejection — в `failed`. При падении `pending` redeliverится обычно, а `attempting` — с видимым recovered marker, потому что возможна копия. Attempts и stale rows ограничены; permanent rejection не должна повторно отправляться как transient reconnect failure.

### Tool execution

Built-in tools обнаруживаются импортом и регистрируются в `tools/registry.py`; `toolsets.py` определяет exposure. `model_tools.get_tool_definitions` фильтрует доступность через `check_fn`, но process-wide availability не является session authorization. Далее идут name/argument validation, inline-tool interception либо registry dispatch, request middleware, pre-tool hooks, ACP edit approval, terminal/file approval, execution middleware, handler и result persistence. Sequential, concurrent и segmented paths обязаны давать одинаковый результат, идентификатор вызова и post-hook semantics.

Approval, redaction, Skills Guard и tool allowlists являются in-process heuristics. Согласно `SECURITY.md`, единственная load-bearing boundary против adversarial LLM — OS isolation: backend sandbox ограничивает shell/file путь, whole-process wrapper также ограничивает plugin, MCP, code execution и hooks.

### Provider routing

Главный runtime resolver выбирает route в ленивом порядке: disabled guard, provider shortcuts, custom/local endpoint, auth/explicit credentials, pool, OAuth/native/external providers, registry API-key providers и OpenRouter/bare-custom fallback. `provider`, `model`, `base_url`, credential и `api_mode` должны оставаться согласованной записью.

Main-agent fallback перебирает `_fallback_chain`, пропускает недоступные записи, строит client через общий resolver и обновляет model/provider/API mode/context/reasoning state. Auxiliary route сначала пробует основной runtime, затем task fallback, main fallback и discovery chain. Credential pool rotation и provider fallback — разные переходы. Отдельно нужно сохранить профильный secret scope и fail-closed поведение multiplex.

## 2. Critical Runtime Invariants

| Область | Инвариант, который нельзя менять незаметно | Как наблюдать |
|---|---|---|
| Сессия | Один активный turn lease не освобождается устаревшим unwind; `run_generation` только возрастает | Concurrent create/resume/close; stale completion; lease rows |
| Роли и prompt | Нет двух одинаковых ролей подряд; system prompt byte-stable на протяжении разговора; compression — единственный санкционированный cache break | Wire-level message transcript и повторный resume |
| Routing | Профиль, platform/chat/thread и session id не смешиваются; session id не является authorization | Два профиля и два caller identity в одной gateway инсталляции |
| Persistence | Shared DB generation закрывается только после release всех владельцев; замена inode не смешивает WAL поколения | Несколько процессов, registry refcount, snapshot/restore race |
| WAL | WAL включается только при подтверждённой совместимости; fallback в DELETE fail-closed при неопределённом режиме | Temp filesystem/forced PRAGMA errors, journal mode readback |
| Startup | Restore и inbound input сериализованы; timeout открывает gate, но не отменяет уже занятый restore slot | Message во время boot restore, delayed task completion |
| Shutdown | Drain считает cron/API/deferred work; cancellation coroutine не считается остановкой worker | Hung executor, active cron/API run, watchdog |
| Delivery | Send acknowledgment определяет `delivered`; ambiguous `attempting` получает recovered marker и не теряется | Crash/restart/reconnect around send await |
| Stream delivery | Draft frames prefix-stable, final объявляет consumer, interim имеет `_interim_send`, reconciliation использует edit | Native streaming adapter contract |
| Tools | Invalid calls не исполняются; valid часть mixed batch не теряется; hooks вызываются один раз; tool/result ids paired | Sequential/concurrent/segmented calls and malformed arguments |
| Approval | Approval context содержит session/turn/call identity; deny/error fail closed | Parallel dangerous tools and approval timeout |
| Security | Allowlist обязательна для network adapter; in-process approval/redaction не выдаётся за sandbox | Unauthorized caller, local versus wrapped backend |
| Provider | Precedence и lazy fallback порядок сохраняются; credentials не перетекают между profiles/providers | Matrix of explicit/custom/local/pool/OAuth/fallback routes |

## 3. Required Regression Tests

Ниже перечислены тесты и существующие наборы, которые должны быть запущены или расширены только в отдельной задаче. Здесь не предлагается реализовывать новые тесты.

### Session and persistence

- `tests/state/test_session_turn_lease.py`, `tests/tui_gateway/test_session_resume_db_ownership.py`, `tests/tui_gateway/test_finalize_session_persist.py`: create/resume/finalize ownership, stale lease and shared DB ownership.
- `tests/gateway/test_compression_session_id_persistence.py`, `tests/agent/test_session_rotation_flush_cold_resume_68454.py`: lineage, compression rotation, transcript flush and cold resume.
- `tests/hermes_state/test_shared_session_db_registry.py`, `tests/hermes_state/test_deleted_wal_generation_guard.py`, `tests/state/test_state_db_wal_unlink_race.py`: registry generations, WAL sidecar deletion and cross-process replacement.
- `tests/test_hermes_state_wal_fallback.py`: WAL incompatibility, DELETE fallback and explicit WAL requirement.
- Add no schema snapshot assertions; verify relationships such as migration reaches current schema and messages remain attached to the owning session.

### Gateway, shutdown and recovery

- `tests/gateway/test_gateway_shutdown.py`, `test_shutdown_executor_quiesce.py`, `test_shutdown_flush.py`, `test_shutdown_watchdog.py`, `test_hygiene_deferred_work_drain.py`: drain, interrupt, persistence flush, watchdog and deferred workers.
- `tests/gateway/test_cron_shutdown_drain.py`, `test_cron_active_work_drain.py`, `test_api_server_active_work_drain.py`: work outside `_running_agents` is counted and not killed prematurely.
- `tests/gateway/test_startup_watchdog.py`, `test_startup_restart_race.py`, `test_pending_drain_race.py`, `test_own_policy_startup_gate.py`: bounded startup gates, queued input and restart races.
- `tests/gateway/test_delivery_ledger.py`, `test_delivery_ledger_producer.py`, `test_restart_redelivery_dedup.py`, `test_restart_drain_recovery_dedup.py`, `test_completion_delivery.py`: ledger state transitions, crash/restart redelivery and duplicate suppression.
- `tests/gateway/test_stream_final_contract.py`, `test_relay_final_delivery_incident.py`, `test_post_stream_media_delivery.py`: prefix/final/edit streaming contracts.
- Live Windows process-topology coverage is required when touching process ownership; follow the `wine2e` rule in `AGENTS.md` instead of faking `sys.platform`.

### Tools and providers

- `tests/tools/test_registry.py`, `tests/run_agent/test_tool_executor_contextvar_propagation.py`, `tests/tools/test_approval.py`, `test_approval_mode_parity.py`, `test_approval_interrupt.py`, `test_write_approval.py`: discovery, context propagation, approval and write safety.
- `tests/gateway/test_allowlist_startup_check.py`, `test_auth_fallback.py`, `tests/tools/test_credential_pool_env_fallback.py`: external authorization and profile credential scope.
- `tests/hermes_cli/test_runtime_provider_resolution.py`, `test_runtime_provider_late_binding.py`, `tests/run_agent/test_provider_fallback.py`, `test_fallback_credential_isolation.py`, `test_fallback_api_mode_preservation.py`, `tests/gateway/test_fallback_chain_reload.py`: precedence, lazy binding, fallback order, credential isolation and native API mode.
- Provider checks must use a temporary `HERMES_HOME` and deterministic credentials/stubs. Never expose real keys in fixtures or logs.

### Eval runs

For a structural baseline, run `evals/codebase_navigability/static_metrics.py` and `runtime_bench.py` against pinned base/candidate trees; verify import provenance. Use `evals/fanout_resource_bench.py` for delegation resource behavior. Use `evals/compaction`, `core_tool_deferral`, `session_search_schema`, `readtool` and `browser_use` only when the change affects their measured contract; each requires repeated paired runs and explicit accounting for infrastructure failures. Evals do not replace lifecycle, SQLite or security regression tests.

Every executed command must record revision, OS, Python/runtime, configuration profile, test selector, exit status, retries/flakiness and unrun gates. “Green” focused tests do not establish delivery, restore, OS process, security or deployment readiness unless those gates ran.

## 4. Migration Safety Gates

Before any future refactor is merged, require these gates in order:

1. **Scope gate:** only intended modules are changed; no API/schema/dependency changes are hidden in an extraction; working-tree changes are preserved.
2. **Ownership gate:** write a table for every moved symbol showing old consumer, new owner, process scope, profile scope, lifecycle and close/release action. Dynamic late imports and `method_ctx` rebinding are included.
3. **Behavior gate:** baseline tests above pass through `scripts/run_tests.sh`; focused failures are investigated rather than masked. No source-text tests or change-detector snapshots.
4. **Persistence gate:** temp-profile SQLite create, WAL/DELETE policy, migration, concurrent read/write, registry generation replacement, recovery and compression lineage pass with real imports.
5. **Lifecycle gate:** startup restore with concurrent inbound, bounded timeout, cron/API/deferred drain, hard interruption, restart and clean exit are exercised. Validate host-native Windows and POSIX paths where relevant.
6. **Delivery gate:** crash windows around `pending → attempting → delivered/failed`, reconnect retry classification and stream-final edit behavior are verified.
7. **Tool/security gate:** registry and inline paths, session grants, approval callbacks, scoped secrets, allowlists and OS isolation assumptions are checked. Do not claim heuristics are containment.
8. **Routing gate:** explicit, custom, local, pool, OAuth/native, auxiliary and exhausted-fallback matrices preserve precedence and credential boundaries.
9. **Eval gate:** applicable evals run in paired pinned trees with repeated reps, cost/resource metrics and infra errors reported separately.
10. **Documentation gate:** update architecture and operational docs for moved symbols; cite unrun checks and unresolved discrepancies. A stale guide is not evidence of current behavior.

Any failed gate blocks the migration claim. A passed unit subset is a partial result, not a GO for runtime refactoring.

## 5. Rollback Strategy

Rollback must be a reversible code deployment to the last baseline revision, preserving user state. Before rollout, record the exact commit, profile/config revision, schema version, process topology and test receipt. Do not use rollback as a reason to downgrade SQLite schema or delete WAL files.

If a refactor causes startup, routing or provider failures, stop new rollout, retain logs and state DB, and restart the previous code with the same profile and external isolation posture. Verify runtime lock/PID ownership before starting a replacement process.

If persistence behavior is suspect, stop write traffic where operationally possible, copy `state.db` with its `-wal`/`-shm` context using the supported recovery procedure, and inspect file identity/generation. Do not manually unlink live WAL/SHM files. Use the existing SessionDB recovery/quarantine tools and verify row counts, FTS rebuild status, session lineage and delivery-obligation counts before resuming.

If delivery is suspect, preserve the ledger. Reconcile `pending`, `attempting`, `failed` and `delivered` rows using the documented markers and attempt limits; never silently mark an ambiguous send delivered. Confirm duplicate-safe redelivery before enabling traffic.

If workers do not drain, use the gateway shutdown/watchdog path, record cron/API/deferred worker counts and only then perform operator-level process termination consistent with the selected OS isolation posture. A killed worker must remain represented as interrupted/resumable where the existing contract requires it.

Rollback acceptance requires: previous revision starts, allowlists/auth work, a known session resumes without role/prompt corruption, state DB opens without generation/WAL errors, no delivery obligation is silently lost, and provider/tool smoke paths use the intended profile credentials. If any item cannot be checked, report rollback as incomplete.

## 6. High Risk Areas

| Risk | Why it is high | Protection required |
|---|---|---|
| Shared SQLite ownership | Registry generations, WAL sidecars, read pools and file replacement cross process/thread boundaries | Real concurrent temp-profile tests; never close or unlink by assumption |
| Session lease and compression lineage | Stale completion can release newer work; compression can rotate IDs and reroute transcript writes | Generation/lease assertions and cold-resume lineage checks |
| Gateway shutdown | Cron/API/deferred workers live outside the main agent map; cancellation is not process termination | Drain/interrupt receipts and host-native process tests |
| Delivery acknowledgement | Crash during send is inherently ambiguous and at-least-once | Ledger transition and duplicate-visible recovery checks |
| TUI/server shared globals | Split handlers are rebound into `server.py` globals; ordinary import analysis misses dependencies | Stdio + WebSocket parity and lifecycle ownership checks |
| Tool approvals | Inline/registry/concurrent paths can diverge in hook order or context identity | Registry-through-dispatch tests, approval timeout/deny/interruption matrix |
| OS security boundary | In-process controls are heuristics; terminal backend does not contain plugins/MCP/code execution | Validate the selected whole-process or backend isolation posture explicitly |
| Provider fallback | Lazy ladder, credential pools, native API modes and fallback prompt identity interact | Precedence matrix, credential isolation and exhausted-chain checks |
| Profile multiplexing | Ambient `os.environ` can leak default-profile secrets or allowlists | Fail-closed scoped reads and cross-profile integration checks |
| Documentation drift | Schema/provider guides may describe prior behavior | Treat source and receipts as oracle; update docs in same migration |

The baseline is protected only when these risks are checked at the boundary they affect. Static review can define the contract and select tests; it cannot certify runtime delivery, OS isolation, provider availability or recovery without executing those paths.

This document is the sole intended artifact for the task. No production code, refactoring, test implementation, API, dependency or schema change was made.
