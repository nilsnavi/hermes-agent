# Current Ownership Map

Дата: 2026-09-19. Это архитектурная карта текущего дерева на основе `runtime-audit.md`, `baseline-protection-plan.md`, `regression-harness-plan.md`, `AGENTS.md` и `SECURITY.md`. Документ не предлагает немедленную реализацию: код, API, классы и расположение модулей не изменялись.

В Hermes «владелец» означает компонент, который принимает решение о состоянии и отвечает за его lifecycle. Модуль, который только вызывает этот компонент или экспортирует фасадное имя, владельцем не считается. Процессный, профильный и session scope должны быть указаны отдельно: shared SQLite не делает Python-объекты общими.

| Responsibility | Current Module | Current Owner | Risk |
|---|---|---|---|
| Gateway startup/access gate | `gateway/run.py`, `gateway/run_startup.py`, `gateway/status.py` | `start_gateway` и `GatewayRunner.start`: runtime lock/PID, policy checks, previous-run recovery, adapter connect, restore gate и status | Startup mixes process ownership, platform wiring, warm-up and recovery; timeout leaves background work alive |
| Gateway shutdown/drain | `gateway/run_shutdown.py` | `GatewayShutdownMixin.stop/_stop_impl` | Active messaging, cron, API and deferred workers have different owners; cancellation is not proof of worker exit |
| Restart/control process | `gateway/run.py`, `hermes_cli/web_server_gateway.py`, update helpers | Gateway control path plus detached action watcher | Desktop backend and standalone gateway have intentional lifetime differences; explicit terminate can defeat detachment |
| Platform adapters | `gateway/platforms/*`, `plugins/platforms/*` | Each adapter owns transport connect/send/disconnect and platform queue | Authorization, streaming finalization and scoped-secret conventions are repeated across adapters |
| Session identity/routing | `gateway/session.py` | `SessionSource`, `SessionEntry`, `SessionStore` routing key and reset policy | Logical routing key, durable session id and task id are easy to conflate |
| Session creation/reset/expiry | `gateway/session_lifecycle.py`, `tui_gateway/methods_session.py` | Gateway lifecycle mixin and TUI RPC handlers for their surfaces | Two surfaces can mutate one durable row; close, archive, delete and lease release are distinct |
| Active turn lease | `gateway/session_lifecycle.py`, `gateway/session_state.py`, state DB markers | Gateway/TUI lease and generation logic | Stale completion can release a newer owner if generation is cleared or bypassed |
| Live per-session memory | `gateway/session_state.py`, `tui_gateway/server.py` globals | Gateway `SessionState`; TUI process-local session registries | TUI split modules are rebound into `server.py` globals; process restart loses live objects |
| Transcript persistence | `gateway/session_transcript.py`, `hermes_state.py` | SessionDB message writer plus transcript reroute/spool logic | Agent incremental flush and gateway transcript append can duplicate unless `skip_db` contract remains |
| Routing index persistence | `gateway/session_persistence.py`, `SessionStore._routing_db` | One routing-home database/index, with optional legacy `sessions.json` mirror | Active profile must not determine the database for a flat multiplex routing index |
| SQLite connection ownership | `hermes_state_registry.py` | Process-wide refcounted `SessionDB` generation per canonical path | Shared `close()` is not release; inode replacement retires old generation until all holders release |
| SQLite schema/migrations | `hermes_state.py`, `hermes_state_common.py`, `hermes_state_schema.py` | SessionDB schema reconciliation and versioned migration code | Stale docs describe old schema; declarative and data migrations have different guarantees |
| WAL/journal policy | `hermes_state_wal.py`, `hermes_cli/sqlite_runtime.py` | `apply_wal_with_fallback` and DB connection setup | Probe/sidecar handling can corrupt locking if a live fd is opened and closed incorrectly |
| DB file health/recovery | `hermes_state_dbfile.py`, `hermes_state_repair.py`, guard/error siblings | Header/identity probes, quarantine, repair and generation checks | Recovery spans filesystem identity, WAL sidecars and active connections; no single transaction owns it |
| Delivery obligations | `gateway/delivery_ledger.py`, gateway startup/shutdown/recovery | SQLite ledger producer plus GatewayRunner redelivery/reconnect paths | Inference completion and transport acknowledgment are separate; ambiguous send is at-least-once |
| Cron execution | `cron/scheduler.py`, `cron/jobs.py`, gateway shutdown counters | Scheduler thread pool and standalone AIAgent per job | Cron runs outside `_running_agents`; shutdown can miss it without the aggregate counter |
| API-server agent runs | `gateway/platforms/api_server.py` | API adapter's active-run accounting and interrupt hooks | Work is outside runner map and must participate in drain/interrupt |
| Deferred agent/tool workers | `gateway/run_shutdown.py`, executor/tool lifecycle | Gateway worker registry and executor futures | Detached executor work can outlive its coroutine and still mutate state |
| Tool discovery/registry | `tools/registry.py`, `model_tools.py`, `toolsets.py` | Registry imports/registers handlers; model_tools resolves schemas; toolsets grants names | Process-wide `check_fn` cache cannot answer session-specific surface authorization |
| Tool execution | `agent/turn_tool_validation.py`, `agent/tool_executor.py`, `model_tools.py` | Agent loop validates/schedules; model_tools middleware dispatches; registry invokes handler | Inline tools bypass registry; sequential/concurrent/segmented paths can diverge |
| Approval/security heuristics | `tools/approval*.py`, terminal/file tools, ACP hooks | Tool-specific guards and callback context | Approval/redaction/allowlist are heuristics, not OS containment under `SECURITY.md` |
| Main provider resolution | `hermes_cli/runtime_provider.py` and backend siblings | Lazy provider ladder builds provider/model/endpoint/credentials/API mode | Several config loaders feed the route; precedence can drift if duplicated |
| Main fallback | `agent/chat_completion_helpers.py`, `agent/auxiliary_client.py` | Agent fallback index/chain, shared client builder and route state | Fallback updates client and prompt/runtime metadata; provider switch interacts with cache rules |
| Auxiliary provider routing | `agent/auxiliary_client.py` | Task route, main route inheritance, task/main fallback and discovery chains | Large mixed-responsibility module; auxiliary behavior is neither fully independent nor identical to main |
| Credential scope | `agent/secret_scope.py`, gateway authz/adapters, credential pool | Profile runtime scope and provider credential sources | Ambient default `os.environ` must not satisfy a scoped secondary profile |
| External authorization | `gateway/authz_mixin.py`, web middleware, platform policies | Surface-specific allowlist/token/OS-user checks | Session IDs are routing handles, not authorization; every network surface needs an allowlist |
| TUI/RPC methods and sessions | `tui_gateway/server.py`, `method_ctx.py`, `methods_*.py` | Python RPC backend owns sessions/tools/models; Ink owns rendering | `types.FunctionType` rebinding hides globals and creates a non-obvious ownership seam |
| Dashboard/serve lifecycle | `hermes_cli/web_server.py`, `web_server_gateway.py` | FastAPI lifespan and detached action management | Ready socket does not prove all background subsystems healthy |

Ownership conflicts are concentrated at boundaries: `SessionStore` versus `SessionDB`, gateway versus cron/API workers, agent versus gateway transcript persistence, registry availability versus session grants, and web/desktop process lifetime versus standalone gateway lifetime.

# Proposed Ownership Model

The following components are application-layer boundaries, not instructions to create them in this task. Their purpose is to name one decision owner while keeping infrastructure details behind interfaces.

| Responsibility | Future Component | Migration Priority |
|---|---|---:|
| Process startup, stop, restart, recovery and worker supervision | `RuntimeApplication` / `RuntimeLifecycleService` | P0 |
| Surface adapter connect, authorization context and event ingress | `SurfaceRuntime` with adapter ports | P1 |
| Session identity, lifecycle transitions, leases, generations and compression lineage | `SessionService` | P0 |
| Routing-index and transcript persistence contracts | `PersistencePort` + `SessionRepository` | P0 |
| SQLite connections, WAL, schema migration, repair and generation registry | `SQLitePersistenceAdapter` | P0 |
| Tool catalog, capability grant, validation, approval and dispatch | `ExecutionService` | P1 |
| Tool result persistence/projection | `ExecutionResultPort` owned by application turn, implemented by persistence/UI adapters | P1 |
| Provider/model/endpoint/credential resolution | `ProviderRouter` | P0 |
| Provider fallback and credential-pool recovery | `ProviderRecoveryPolicy` under `ProviderRouter` | P0 |
| Main/auxiliary route distinction | `ProviderRouter` with explicit `RoutePurpose` (main, compression, vision, title, search) | P1 |
| Delivery obligation state machine and send acknowledgment | `DeliveryService` | P0 |
| Platform-specific transport behavior | Adapter implementations behind `DeliveryPort` | P1 |
| Cron job scheduling and delivery target selection | `JobService` using `SessionService`, `ProviderRouter` and `DeliveryService` ports | P1 |
| TUI/HTTP/CLI request translation | Surface controllers, not domain owners | P2 |

The application layer should own orchestration and invariants: one session transition, one lease decision, one route decision, one delivery state transition. It should not own SQLite pragmas, provider SDK objects, PTY details or platform-specific message formatting.

## Recommended future boundaries

`RuntimeApplication` receives a surface event, establishes profile/session context, asks `SessionService` for ownership, asks `ProviderRouter` for a route, invokes `ExecutionService` through the agent turn, persists through ports, and hands the final obligation to `DeliveryService`. It also owns the shutdown protocol: stop intake, mark recoverable work, drain all worker classes, interrupt after deadlines, release resources and persist exit state.

`SessionService` owns the state machine, not the storage implementation. It knows the difference between logical routing key, durable session id and task id; controls create/resume/reset/expire/close; validates concurrent ownership; preserves generations; and records compression parent/tip transitions. It delegates row/message operations to `SessionRepository` and does not open raw SQLite connections.

`PersistencePort` separates repository semantics from `SQLitePersistenceAdapter`. The adapter owns connection registry, WAL/DELETE selection, migrations, file identity, repair, FTS and generation retirement. Delivery obligations may share the physical database but retain a separate repository/state machine and transaction contract.

`ExecutionService` owns the single semantic tool pipeline. Registry discovery, inline tool table, availability and platform-specific handlers remain infrastructure/plugins. The service owns validation, capability grant, approval context, concurrency policy, hook ordering and result projection. A `check_fn` can answer reachability; it cannot decide whether a remote session is a GUI or provide containment.

`ProviderRouter` returns an immutable route record containing provider, model, base URL, API mode, credential reference and purpose. It preserves the current lazy precedence and fallback chain, but credential material stays in a credential port and provider SDK construction stays in adapters. Prompt-cache behavior on provider switch must be an explicit policy decision before moving fallback code.

`DeliveryService` owns obligation transitions and retry classification. Adapters only report send outcomes and expose edit/send operations. The service decides whether `pending`, `attempting`, `failed` or `delivered` can advance, whether a recovered marker is required, and when an ambiguous operation is visible to the user.

# Dependency Boundaries

The target dependency direction is:

```text
interfaces / ports
        ↓
application services
        ↓
domain state machines and value objects
        ↓
infrastructure adapters (SQLite, transports, providers, tools, OS/processes)
```

### Allowed dependencies

- Surface controllers may depend on application interfaces and translate CLI, RPC, HTTP or platform events into neutral commands.
- Application services may depend on domain objects and declared ports. They may not inspect SQLite connections, environment variables or provider SDK internals directly.
- Domain objects may depend on standard-library value types and policy interfaces; they must not import gateway adapters, FastAPI, Ink/RPC, `sqlite3`, provider SDKs or tool subprocess code.
- Infrastructure adapters implement ports and may depend on their own SDK/filesystem/process APIs. They may emit typed outcomes, not decide unrelated session or application policy.
- Cross-cutting logging/metrics may observe transitions through explicit hooks; it must not become a second state owner.

### Forbidden dependencies

- A platform adapter directly mutating `SessionDB` rows or releasing a lease it did not acquire.
- A surface deciding provider fallback, changing credential scope, or bypassing `ProviderRouter`.
- Tool handlers reaching into gateway runner dictionaries, TUI globals or another tool's approval state.
- `check_fn` or an environment variable deciding client surface capability; surface belongs to session context/toolset resolution.
- Application/domain code importing `hermes_cli` loaders opportunistically to obtain defaults; precedence must be passed through a route/config port.
- Closing or unlinking SQLite/WAL files from a caller that does not own the DB generation.
- Delivery adapters marking a message delivered before the transport acknowledges success.
- A refactor adding internal re-export shims or new compatibility paths to conceal an ownership move.
- Plugins or skills being treated as a security boundary: they execute in the agent process with agent privileges.
- Gateway shutdown counting only `_running_agents`; cron, API and deferred workers must remain visible to lifecycle ownership.
- New core tools or speculative hooks when an existing CLI/skill/service-gated tool/plugin/MCP boundary is sufficient.

## Ownership records required for any move

Before moving a symbol, record: current and future owner; process and profile scope; authoritative state; mutation methods; initialization trigger; shutdown/release action; failure/retry policy; persistence transaction; security principal; and the tests/evals that prove the contract. Late imports and `tui_gateway.method_ctx` rebinding must appear in the record because static import graphs do not reveal their ownership.

# Migration Order

1. **Freeze the baseline and terminology.** Use the regression harness golden suite, record current process ancestry and write an ownership table for the selected slice. Resolve documentation discrepancies (provider fallback and schema version) from source before changing consumers. Risk: a wrong owner map makes every later extraction appear safe.

2. **Extract persistence ports behind existing behavior.** Start with read/write interfaces for sessions, routing, messages, delivery obligations and usage while leaving `SessionDB`, registry and WAL code intact. Prove shared-handle, generation replacement, WAL fallback and recovery contracts with temporary profiles. Risk: persistence mistakes can lose or duplicate state and are hard to repair after a schema change.

3. **Establish `SessionService`.** Move lifecycle decisions conceptually first: identity normalization, create/resume/close, leases, generations, expiry and compression lineage. Keep routing index and transcript repositories separate. Run concurrent resume/close and rotation/cold-resume scenarios. Risk: stale generation or cross-profile writes can affect unrelated conversations.

4. **Establish `DeliveryService`.** Place the ledger transition policy and retry classification behind one owner; keep platform send/edit APIs in adapters. Verify crash windows, reconnect redelivery and streaming final contracts. Risk: delivery is inherently at-least-once around an ambiguous network acknowledgment.

5. **Establish `RuntimeApplication` lifecycle.** Make startup gate, background worker registry, drain/interrupt deadlines and shutdown finalization explicit while preserving gateway control behavior. Include cron, API-server and deferred workers, detached actions and native OS process semantics. Risk: a superficial lifecycle wrapper can orphan workers or terminate the wrong gateway.

6. **Establish `ProviderRouter`, then `ExecutionService`.** Provider routing precedes tool execution because agent construction determines tool grants, context limits and API mode. Preserve lazy resolver order, credential isolation, auxiliary purpose and fallback prompt policy. Then unify tool validation/approval/hook/result semantics across inline and registry paths. Risk: these are broad fan-out boundaries used by CLI, gateway, cron, TUI and plugins.

7. **Migrate surfaces last and delete obsolete ownership only after receipts are green.** CLI, gateway, TUI/RPC, dashboard and cron become thin controllers/adapters over application services. Run applicable regression tests and paired evals at every slice; keep rollback to the previous revision and state format. Risk: surface-specific behavior (busy guards, PTY, streaming, allowlists) is easy to erase during “cleanup”.

This ordering intentionally puts persistence and session contracts before lifecycle orchestration, and lifecycle before broad provider/tool extraction. No step authorizes code changes in this document; it defines the ownership and evidence required for a separately approved implementation task.

Architecture acceptance: current ownership conflicts are named, future boundaries are explicit, dependency direction and forbidden shortcuts are recorded, and migration order includes risk and validation obligations. This file is the only artifact created for this task.
