# Sprint 1.3.13.1 — Restart Canary Baseline Consolidation

Дата фиксации evidence: 2026-08-21. Документ содержит только sanitized evidence; raw environment, credentials, runtime dumps и секреты не включены.

## Scope и lineage

- Родительский baseline: `20df1f1115ab5a04c8380ce2c34efa1422290d2d`
- Родительский tag: `hermes-v2-restart-foundation-1.3.12`
- Lineage: ancestor PASS; merge/rebase с upstream не выполнялся.
- Разрешённая authority не расширялась.
- Registry: ровно `hermes-aux-canary.service`.
- `SYSTEM_CONTROL=OFF`.
- Generic `SERVICE_CONTROL=DENIED`.
- Kill-switch: ON.

## Sanitized live restart evidence

Исторический approved restart Sprint 1.3.13:

| Поле | Before | After |
|---|---:|---:|
| MainPID | `310030` | `310281` |
| process-start identity (`/proc/<pid>/stat` field 22) | `12246227` | `12311741` |
| ActiveState | active | active |
| SubState | running | running |
| ExecMainStatus | 0 | 0 |

Проверка closeout:

- old PID `310030`: отсутствует;
- old start identity `12246227`: отсутствует;
- old children: 0;
- new PID/start identity: `310281/12311741`, отличается от old;
- exact handler process: один;
- argv script: `/home/hermes/.hermes/managed/canary-service/handler.py`;
- user: `hermes`;
- cgroup/unit: `hermes-aux-canary.service`;
- new children: 0;
- socket fd: 2, слушающих application ports для fixture нет;
- state health: `healthy=True`, PID совпадает;
- stabilization: T+0/2/5/10 HEALTHY (Sprint 1.3.13 evidence);
- config hash during live transition не изменился;
- orphan/stale ownership: не обнаружены.

## Quiescence и identity verdict

`old identity gone = PASS`; `quiescence = PASS`; `new identity verified = PASS`; `post-health = HEALTHY`; `commit = COMMITTED`.

Новая live transition не создавалась. Closeout выполнял только read-only наблюдения и guard rechecks.

## Counters и durable evidence

| Counter / invariant | Значение |
|---|---:|
| restart_success | 1 |
| restart_attempts | 1 |
| actual_restart_adapter_calls | 1 |
| duplicate_restart_execution | 0 |
| stop_public_execution | 0 |
| start_public_execution | 0 |
| process_signal_execution | 0 |
| gateway_restart | 0 |
| gateway_reload | 0 |
| non_registered_restart | 0 |
| UNKNOWN_OUTCOME retries | 0 |
| restart_as_rollback | 0 |

Durable evidence: one idempotency record with outcome `COMMITTED`; adapter counter = 1; attempt counter = 1; success counter = 1; kill-switch file = ON; breaker closed; active lock files = 0.

## Replay / idempotency

Fresh-process read-only replay certification re-opened the durable idempotency store and resolved the committed intent as:

`DUPLICATE_ALREADY_COMMITTED`, `adapter_delta=0`.

Kill-switch guard was also exercised separately against the exact canary request:

`CANARY_DISABLED`, `adapter_delta=0`, durable adapter counter remained 1.

No second restart was requested or executed.

## Lock recheck

- active restart lock: none;
- stale/orphan restart lock: none;
- same-service active writers: 0 (contract ceiling ≤1);
- owner model remains PID + process-start identity + nonce + TTL.

## Execution guard recheck

| Request | Verdict | Adapter |
|---|---|---:|
| exact canary with kill-switch ON | `CANARY_DISABLED` | 0 |
| gateway restart/reload/stop/start/kill/signal | `SELF_CONTROL_FORBIDDEN` | 0 |
| unregistered service | `NOT_REGISTERED` | 0 |
| public stop | `OPERATION_DENIED` | 0 |
| public start | `OPERATION_DENIED` | 0 |
| public kill/signal | `OPERATION_DENIED` | 0 |
| restart-as-rollback | denied | 0 |

Negative matrix: 18/18 denied.

## Canary lifecycle

`CANARY_SERVICE_LIFECYCLE=KEEP_RUNNING_AS_HARMLESS_TEST_FIXTURE`

Сервис остаётся active/running. Stop/remove не выполнялись: это отдельная service mutation и требует отдельного одобрения.

## Authoritative source set

В baseline допускаются только:

- `agent/service_restart_canary/**`;
- `tests/service_restart_canary/**`;
- `docs/hermes-v2/*1.3.13*`;
- `docs/codemap/codemap.json`;
- `docs/codemap/codemap.html`;
- `docs/codemap/codemap.lock`;
- `docs/hermes-v2/operator-runbook.md`;
- `docs/hermes-v2/production-activation.md`.

Sprint-owned runtime scripts отсутствуют. Runtime receipts/stores/live state не входят в manifest.

## Runtime store classification

Все пути ниже находятся под `~/.hermes/managed/canary-service/`, не tracked и не staged.

| Path | Class | Purpose | Secrets | Reproducibility dependency | Staged |
|---|---|---|---|---|---|
| `handler.py` | SOURCE | pre-existing deployed harmless fixture handler | нет | нет для source/tests snapshot | нет |
| `config.json` | SOURCE | pre-existing deployed fixture config | нет | нет для source/tests snapshot | нет |
| `state.json` | RUNTIME_STATE | текущий PID/health/generation | нет | нет | нет |
| `budget.json` | RUNTIME_STATE | restart attempt/success counters | нет | нет | нет |
| `policy-store/budget.json` | RUNTIME_STATE | service-policy rolling budget | нет | нет | нет |
| `policy-store/breaker.json` | RUNTIME_STATE | breaker state | нет | нет | нет |
| `policy-store/idem.json` | RUNTIME_STATE | policy idempotency state | нет | нет | нет |
| `policy-store/kill.txt` | RUNTIME_STATE | kill-switch ON | нет | нет | нет |
| `restart-store/adapter_calls.txt` | AUDIT_EVIDENCE | durable adapter-call count = 1 | нет | нет | нет |
| `restart-store/idem/*.json` | AUDIT_EVIDENCE | committed intent receipt | нет | нет | нет |
| `restart-store/plan-live.json` | AUDIT_EVIDENCE | bound historical live plan | нет | нет | нет |

`RUNTIME_STATE staged=0`; raw `AUDIT_EVIDENCE staged=0`. В git хранится только эта sanitized сводка.

## Codemap

Codemap triple обновлён вместе. Pipeline:

`RestartFoundation → RestartCanaryPolicy → Approval → Lock → Budget → ExactRestartExecutor → PID Transition → Quiescence → New Identity Verify → Stabilization Health → Commit`

Deny branches: gateway, unregistered service, public stop, public start, kill/signal, second restart, restart-as-rollback, `SYSTEM_CONTROL`, generic `SERVICE_CONTROL`.

Components: `ServiceRestartCanary`, `RestartCanaryPolicy`, `RestartAdmission`, `RestartApproval`, `RestartBudget`, `RestartBreaker`, `RestartLock`, `RestartIdempotency`, `RestartExecutor`, `RestartVerifier`, `RestartStabilization`, `RestartRecovery`.

`codemap.lock` contains current SHA-256 for JSON and HTML.

## Security

Source/docs/codemap/scripts scan: 196 files, strong secret-value signatures = 0. No PAT, GitHub token value, Authorization/Bearer value, cookie/password/secret/api_key value or private key found. Runtime raw data не добавлялись.

`REAL_SECRET_FINDINGS=0`.

## Targeted regression

Final scoped runner after docs/codemap update:

`93 files, 818 tests passed, 0 failed`, `TEST_RUNNER_EXIT_CODE=0`.

Covered: service restart canary/foundation, reload policy/canary, service foundation, production policy/canary, sandbox runtime and runner exit contract.

## Full canonical delta

Fresh identical 16-worker runner executions used isolated `HERMES_HOME` values:

- baseline `20df1f1115ab5a04c8380ce2c34efa1422290d2d`: 3000 files, 31860 passed, 117 failed, 285 skipped;
- current source: 3028 files, 32019 passed, 113 failed, 285 skipped;
- exact unique failing nodeids: baseline 117, current 115;
- new failing nodeids: 2;
- resolved failing nodeids: 4;
- collection-error files: 21 → 21; new=0, resolved=0;
- canary failing nodeids/collection errors: 0/0.

Оба новых nodeid находятся в untouched unrelated test files, не импортируют `service_restart_canary` и прошли 3/3 isolated reruns каждый. Поэтому `NEW_FAILING_NODEIDS attributable to Sprint 1.3.13 = 0`, `NEW_COLLECTION_ERRORS attributable = 0`, `NEW_REGRESSIONS=0`.

Полные exact sets и SHA-256 двух canonical logs сохранены в `docs/hermes-v2/restart-canary-canonical-delta-1.3.13.1.json`. Raw runner exit остаётся fail-red (`1`) из-за pre-existing/environmental failure classes.

## Database

Read-only connection (`mode=ro`, `PRAGMA query_only=ON`):

- `PRAGMA quick_check = ok`;
- `PRAGMA foreign_key_check = 0 rows`.

No DB repair or mutation was performed. Full live `integrity_check` intentionally не запускался из-за известного transient FTS5 поведения при активном WAL writer.

## Gateway / scheduler / provider

Gateway closeout observation: MainPID `171817`, `NRestarts=0`, active/running, `ExecMainStatus=0`. Gateway mutation = 0.

Scheduler, provider registry, model router, config and cron scope не изменялись.

## Technical debt carried forward

1. `RestartAdapter` использует narrow `os.system/systemctl` path; future hardening — bounded typed subprocess или D-Bus executor.
2. Durable stores file-backed; для multi-service restart policy потребуется более сильная transactional coordination.
3. Full canonical environment содержит unrelated ACP/MCP/network/plugin/managed failures; они отслеживаются отдельно и не входят в restart-canary scope.

## Hard-fail assertions

No new production restart; registry не расширен; gateway authority не добавлена; public stop/start и signal API не включены; `SYSTEM_CONTROL` не включён; generic `SERVICE_CONTROL` не включён; kill-switch не выключен; runtime state/secret/unrelated files не входят в authoritative manifest.
