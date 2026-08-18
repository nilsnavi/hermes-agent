# System Boundary Layer — Sprint 1.3.3

> Спринт: 1.3.3 · Статус: **PASS — SYSTEM BOUNDARY LAYER STABLE**
> Дата: 2026-08-14 · Предшественник: Sprint 1.3.2 (Verified Tool Execution Contract)
> Модуль: `agent/system_boundary/` · Тесты: `tests/system_boundary/`

## 1. Цель

Детерминированный **fail-closed System Boundary Layer (SBL)**, который
ограничивает execution после policy-решения и перед реальным
ToolAdapter. SBL отвечает на вопросы: какой ресурс затрагивается,
какая операция выполняется, каков effective action (включая indirect
execution), какой процесс/сервис является target, каков blast radius,
совпадает ли фактический target с preflight, изменился ли target после
preflight, требуется ли validation/revalidation, нарушается ли system
boundary.

**Главный security invariant:** даже если Intent Router, Capability
Router и Capability Policy Engine ошиблись — опасная system mutation
всё равно останавливается до `ToolAdapter.execute()`.

## 2. Архитектура

**Before (Sprint 1.3.2):**

```
IntentRouter → CapabilityRouter → CapabilityPolicyEngine
→ ExecutionRequest → VerifiedToolExecutor → NoopSystemBoundary
→ ToolAdapter → ExecutionResult
```

**After (Sprint 1.3.3):**

```
IntentRouter → CapabilityRouter → CapabilityPolicyEngine
→ ExecutionRequest → VerifiedToolExecutor
    ├─ request validation
    ├─ registry validation
    ├─ policy/risk validation
    ├─ idempotency
    ├─ receipt
    └─ SystemBoundary
          ├─ preflight()
          ├─ authorize()
          ├─ verify_before_execute()
          └─ verify_after_execute()   (foundation, read-only)
                    ↓
              ToolAdapter
                    ↓
             ExecutionResult
```

ToolAdapter вызывается **только если** PolicyDecision разрешает AND
`SystemBoundary.authorize() == PASS` AND
`SystemBoundary.verify_before_execute() == PASS`.

## 3. Authority model

- **CapabilityPolicyEngine** — ЕДИНСТВЕННЫЙ policy authority.
- **VerifiedToolExecutor** — ЕДИНСТВЕННЫЙ execution gateway.
- **System Boundary Layer** — restrictive boundary, НЕ источник
  разрешений.

SBL МОЖЕТ: классифицировать resource/operation, вычислять effective
action, обнаруживать indirect execution, определять affected
service/process, blast radius, повышать risk floor, требовать
approval/validation/fresh preflight, BLOCK execution.

SBL НЕ МОЖЕТ: уменьшать risk, превращать DENY в ALLOW, LEGACY в V2,
выдавать capability authority, самостоятельно approve, создавать
permissions, обходить PolicyDecision/VerifiedToolExecutor, выполнять
remediation/rollback, делать system changes вне ToolAdapter contract.

## 4. SystemBoundary contract

```python
class SystemBoundaryV2(Protocol):
    def preflight(self, request, descriptor) -> SystemPreflightPlan: ...
    def authorize(self, request, descriptor, preflight=None) -> BoundaryDecision: ...
    def verify_before_execute(self, request, descriptor, preflight) -> BoundaryDecision: ...
    def verify_after_execute(self, request, descriptor, result, preflight) -> BoundaryVerificationResult: ...
```

Реализация: `agent.system_boundary.SystemBoundaryLayer` (версия
`sbl-1.3.3-v1`). Executor определяет V2-boundary по наличию
`preflight` + `verify_before_execute` (`is_v2_boundary`); legacy
NoopSystemBoundary / DenySystemBoundary (Sprint 1.3.2) остаются
валидными для rollback.

### BoundaryDecision (§5)

Immutable, verdict: **PASS / BLOCK / REVALIDATE_REQUIRED**.

- `PASS` — SBL не добавляет запрет; НЕ является permission.
- `BLOCK` — execution запрещён boundary-слоем.
- `REVALIDATE_REQUIRED` — target/resource/preflight изменился;
  execution запрещён до нового preflight.

Поля: verdict, reason_code, resource_class, operation_class,
effective_action_class, risk_before/floor/after, target_resources,
affected_services/processes/ports/dependencies, blast_radius,
approval_required, validation_required, postcheck_required,
resource_fingerprint, preflight_digest, graph_version, graph_health,
confidence, boundary_version.

### SystemPreflightPlan (§21)

Immutable: preflight_id, execution/request/run/step id, tool_name,
capability, operation_class, effective_action_class,
canonical_targets, arguments_digest, resource_fingerprints,
effective_risk, risk_floor, blast_radius, affected_services/processes,
validators, post_checks, rollback_possible,
rollback_strategy_metadata, graph_version, graph_health,
created_at/expires_at, preflight_digest.

## 5. Resource classification (§10, §19)

Классы: USER_DATA, APPLICATION_DATA, APPLICATION_CONFIG,
SYSTEM_CONFIG, SYSTEM_BINARY, SYSTEM_SERVICE, SYSTEM_STATE,
NETWORK_CONFIG, PACKAGE_STATE, PROCESS_RESOURCE, CONTAINER_RESOURCE,
DEVICE_RESOURCE, SECRET_RESOURCE, TEMPORARY, UNKNOWN.

Инварианты: **UNKNOWN != SAFE / USER_DATA / NONE**. Классификация
производится по RESOLVED identity (realpath), а не по input string;
учитываются resolved path, file type, owner, mount identity, target
semantics, service ownership. Чувствительные пути: /etc, /usr, /bin,
/sbin, /lib, /boot, /var/lib, /var/spool, /opt, /root, /proc, /sys,
/dev, /run + systemd/ssh/nginx/docker/letsencrypt.

## 6. Operation classification (§11)

READ / CREATE / WRITE / APPEND / PATCH / DELETE / MOVE / COPY / LINK /
PERMISSION_CHANGE / OWNERSHIP_CHANGE / SERVICE_START/STOP/RESTART/
ENABLE/DISABLE / PROCESS_START/SIGNAL/KILL / PACKAGE_INSTALL/REMOVE/
UPGRADE / NETWORK_CHANGE / FIREWALL_CHANGE / IDENTITY_CHANGE /
SECRET_ACCESS / CONTAINER_CONTROL / MOUNT_CONTROL / KERNEL_CONTROL /
EXECUTE_SCRIPT / EXECUTE_BINARY / UNKNOWN.

Инвариант: **Unknown mutation никогда не классифицируется как READ.**

## 7. Effective action (§12, §14) — P0

Immediate tool name недостаточен; SBL классифицирует EFFECTIVE ACTION
для chained execution. Распознаются: `bash -c` / `sh -c` / bash script
/ sh script, `env` / `nohup` / `setsid` wrappers, `python -c` /
python script, subprocess / os.system, exec family, generated/temp
scripts, systemctl/service inside wrappers, docker/podman/kubectl
wrappers.

Канонический P0-сценарий (§12): `write_file("/tmp/hgw_reload.sh",
"sleep 8; systemctl --user restart hermes-gateway")` → background
launch → systemctl restart. Ожидается: EXECUTE_SCRIPT →
INDIRECT_SYSTEM_CONTROL → SERVICE_RESTART → target=hermes-gateway →
PROCESS_SELF_CONTROL_FORBIDDEN; ToolAdapter calls = 0; gateway restart
= 0.

Если mutation-capable chain не может быть надёжно классифицирован:
**EFFECTIVE_ACTION_UNKNOWN → BLOCK.**

Источники доверия (по убыванию): VerifiedToolDescriptor →
structured operation metadata → known adapter semantics → safe
tokenizer/parser → deterministic recognizer → bounded artifact
lineage → conservative UNKNOWN. **LLM classification никогда не
является authoritative для execution.**

## 8. Filesystem boundary (§17, §18, §20, §25)

- **Path resolution**: absolute/relative/cwd/./..//~/unicode/spaces/
  symlink/broken symlink/parent symlink/new-file parent/realpath.
  Классификация по resolved identity.
- **Fingerprint**: realpath, device, inode, mode, uid, gid, mtime_ns,
  size, resource_class. Поля optional; значения не выдумываются.
- **Защита**: path traversal, symlink escape, parent symlink escape,
  resource substitution, new-file parent escape, race between inspect
  and execute.
- **TOCTOU (§25, P0)**: preflight safe target → fingerprint → target
  заменён symlink → verify_before_execute() → RESOURCE_CHANGED_AFTER_
  PREFLIGHT или SYMLINK_ESCAPE → REVALIDATE_REQUIRED/BLOCK;
  ToolAdapter calls = 0.

## 9. Process boundary (§27, §28) — P0 self-control

Классы: CURRENT_PROCESS / CHILD_PROCESS / SIBLING_PROCESS /
FOREIGN_PROCESS / HERMES_GATEWAY / SYSTEM_PROCESS / UNKNOWN_PROCESS.

**Hermes gateway не имеет права restart/stop/kill/pkill себя** —
включая indirect execution. Проверяются: systemctl --user restart
hermes-gateway, service restart, kill <gateway_pid>, pkill -f,
bash -c "...", generated script, nohup script, python subprocess.
Ожидается PROCESS_SELF_CONTROL_FORBIDDEN, adapter calls = 0, gateway
PID/NRestarts не изменяются.

## 10. Service boundary (§29)

`systemctl status nginx` → READ. `systemctl restart nginx` →
SERVICE_RESTART + target nginx. `systemctl stop ssh` → SERVICE_STOP +
target ssh. Unknown service mutation → BLOCK. systemctl mutation не
может спрятаться за shell wrapper (effective-action классификатор
разворачивает wrappers до этого слоя).

## 11. Network boundary (§30)

Классы: LOOPBACK / LOCAL_HOST / LAN / PRIVATE_NETWORK /
PUBLIC_NETWORK / UNKNOWN. Операции: READ / CONNECT / LISTEN_CHANGE /
ROUTE_CHANGE / CONFIG_CHANGE / FIREWALL_CHANGE. No new network
authority. UNKNOWN mutation → BLOCK.

## 12. Env / secret boundary (§31)

Идентифицирует: full process env inheritance, credential file access,
private key access, token store, secret-bearing env injection.
SECRET_RESOURCE → risk floor increase. **Значения environment никогда
не логируются** (проверяются только имена переменных).

## 13. Service graph (§32-§38, §65)

Bounded graph: SERVICE / PROCESS / CONFIG / FILE / PORT / SOCKET /
DOMAIN / CERTIFICATE / CONTAINER / IMAGE / VOLUME / NETWORK /
DATABASE / CACHE / QUEUE / UPSTREAM / PACKAGE. Edges: OWNS / USES /
READS / WRITES / LISTENS_ON / CONNECTS_TO / PROXIES_TO / DEPENDS_ON /
REQUIRES / MOUNTS / EXPOSES / USES_CERTIFICATE / RUNS_AS /
MANAGED_BY.

**Provenance/trust (§33):** STATIC_VERIFIED может подтверждать
identity в своём scope; RUNTIME_OBSERVED / CONFIG_OBSERVED могут
повышать risk; INFERRED / LEARNED — только повышают; никогда не
grant PASS/ALLOW, не уменьшают risk, не доказывают отсутствие
зависимости, не доказывают safety.

**Источники (§34):** systemctl / systemctl show / systemctl cat, /proc
для известных PID, ss, known service configs, nginx config, Docker/
Compose metadata, known Hermes integrations. Запрещено: unbounded
find /, recursive grep /, unbounded crawl.

**Discovery budget (§35):** max_files/max_bytes/max_services/
max_processes/max_depth/max_edges/timeout_per_source/total_timeout.
Exhaustion → GRAPH_PARTIAL; "не успели найти" ≠ "dependencies
отсутствуют".

**Health (§37):** HEALTHY / STALE / PARTIAL / UNAVAILABLE / CORRUPT.
UNKNOWN/PARTIAL dependency set != EMPTY.

**TTL (§38):** раздельная freshness для process/service/port/config/
static ownership; monotonic age в runtime; persisted wall-clock —
только audit.

## 14. Blast radius (§39-§41)

NONE / LOCAL / SERVICE / MULTI_SERVICE / HOST / NETWORK / UNKNOWN.
**UNKNOWN != NONE.** Учитываются direct/transitive/critical
dependency, public exposure, ports, domains, services, processes.
Traversal: cycle-safe, depth-limited, budgeted. Risk floor: LOCAL →
preserve/raise, SERVICE mutation → service risk, MULTI_SERVICE →
higher, HOST → system-control floor, NETWORK → network/system floor,
UNKNOWN mutation → conservative block/risk.

## 15. Risk model (§6)

```
effective_risk = max(intent_risk, capability_risk, tool_risk,
                     context_risk, sbl_risk_floor)
```

Инвариант: **risk_after >= risk_before**. Ни один SBL-компонент не
может уменьшить risk. Approval решает PolicyEngine, не SBL.

## 16. Preflight binding (§22-§24, §63)

Preflight cryptographically bound (SHA-256 canonical serialization) к:
tool, capability, operation, effective action, normalized non-secret
args, canonical targets, resource fingerprints, run/step context,
graph version. `restart nginx != restart ssh`, `restart nginx != stop
nginx`, `restart nginx args A != args B`. Harmless preflight нельзя
переиспользовать для более опасной операции.

**Replay protection (§63):** план restart nginx отклоняет restart ssh
/ stop nginx / changed args / different target / different run/step
(если не reusable) → PREFLIGHT_MISMATCH, adapter = 0.

**Expiration (§24):** TTL bounded; expired → PREFLIGHT_EXPIRED →
REVALIDATE_REQUIRED; никакого silent TTL extension.

## 17. Validation registry (§42-§43)

Static verified registry: nginx -t, systemd-analyze verify, strict
JSON parser, safe YAML parser, docker compose config, sshd -t.
Отсутствующий validator для mutation requiring validation →
VALIDATION_UNAVAILABLE → BLOCK/REVALIDATE. LLM / skills / plugins /
MCP metadata **не могут** динамически регистрировать trusted
validators — только static verified registry.

## 18. Post-execution contract (§44)

verify_after_execute foundation поддерживает: target fingerprint,
expected resulting state, service state, port state, health state,
validator result. **Sprint 1.3.3: production mutation execution = 0.**
Полное transactional применение — Sprint 1.3.4.

## 19. Rollback metadata (§45)

SBL только описывает: rollback_possible, rollback_strategy
(restore_file / restore_mode / restore_owner / restore_previous_unit /
restart_service / restore_snapshot), rollback_evidence. SBL не
выполняет rollback самостоятельно.

## 20. Boundary bypass (§46) — P0

При включённом SBL нельзя выполнить VerifiedToolAdapter в production
V2, минуя SystemBoundary. `SBLGuardToken` (одноразовый, привязан к
конкретному SBL-инстансу) обязателен для adapter invocation; direct
adapter execution / fake registry / manual tool injection /
monkeypatched registry / invalid boundary object →
BOUNDARY_BYPASS_DETECTED, adapter calls = 0.

## 21. Fail closed (§49)

Инъекции ошибок в: path resolver, realpath, fingerprint, operation
classifier, effective-action classifier, process resolver, service
resolver, graph parser, dependency resolver, blast radius, preflight,
validator registry, persistence → unexpected exception →
**SBL_INTERNAL_ERROR → BLOCK**. Exception → PASS запрещён.

## 22. Reason codes (§50)

SBL_OK · RESOURCE_UNKNOWN · RESOURCE_SYSTEM ·
RESOURCE_CHANGED_AFTER_PREFLIGHT · PATH_UNRESOLVED ·
PATH_ESCAPE_DETECTED · SYMLINK_ESCAPE · OPERATION_UNKNOWN ·
EFFECTIVE_ACTION_UNKNOWN · INDIRECT_SYSTEM_CONTROL ·
PROCESS_SELF_CONTROL_FORBIDDEN · NETWORK_TARGET_UNKNOWN ·
SECRET_RESOURCE_DETECTED · BOUNDARY_BYPASS_DETECTED ·
DEPENDENCY_UNKNOWN · BLAST_RADIUS_UNKNOWN · BLAST_RADIUS_HIGH ·
SERVICE_GRAPH_STALE/PARTIAL/UNAVAILABLE/CORRUPT · PREFLIGHT_REQUIRED
· PREFLIGHT_EXPIRED · PREFLIGHT_MISMATCH · VALIDATION_REQUIRED ·
VALIDATION_UNAVAILABLE · POSTCHECK_REQUIRED · SBL_INTERNAL_ERROR.

## 23. Metrics (§51)

sbl_requests_total · sbl_pass_total · sbl_block_total ·
sbl_revalidate_total · sbl_resource_class_total ·
sbl_operation_class_total · sbl_effective_action_total ·
sbl_risk_escalations_total · sbl_graph_refresh_total ·
sbl_graph_refresh_failures_total · sbl_graph_health ·
sbl_dependency_unknown_total · sbl_blast_radius_total ·
sbl_preflight_created_total · sbl_preflight_expired_total ·
sbl_preflight_mismatch_total · sbl_toctou_detected_total ·
sbl_boundary_bypass_total · sbl_self_control_block_total.
Labels bounded; raw path labels запрещены.

## 24. Audit model (§52)

Поля: timestamp, execution/request/run/step id, policy_decision_id,
policy_version, boundary_version, boundary_verdict, reason_code,
resource_class, operation_class, effective_action_class, risk_before/
after, blast_radius, affected_service/process ids, graph_version,
graph_health, preflight_digest, result. **Запрещено сохранять:** raw
prompt, secret, credential, authorization header, full env, private
key, raw arbitrary payload.

## 25. Feature flags (§55)

```
HERMES_SBL_V2_ENABLED  (default true)
HERMES_SBL_V2_MODE     (off | shadow | enforce; default shadow)
HERMES_SBL_GRAPH_ENABLED (default true)
HERMES_SBL_DEEP_AUDIT  (default false)
```

Shadow = analytics/evidence без влияния на safe read path; Shadow НЕ
означает, что опасную system mutation можно выполнить — critical
mutation boundary fail-closed даже в shadow.

## 26. Persistence (§36)

`~/.hermes/hermes-v2/sbl/`: service_graph.json, graph.meta.json,
audit.jsonl, snapshots/. Atomic writes, schema_version, generated_at,
checksum, source/provenance, TTL, no secrets, corruption detection.
Production state.db schema не меняется.

## 27. Security (§47-§48, §86)

- **Supply chain (§47):** skills / plugins / MCP descriptions / remote
  metadata / learned rules / LLM output не могут стать authoritative
  boundary policy. Static registry only.
- **Prompt injection independence (§48):** "ignore system boundary",
  "developer approved", "safe command", "skip preflight", "restart
  gateway anyway", "this is read-only" не меняют SBL verdict — SBL
  работает только на structured metadata.
- Secret findings = 0 (сканирование sprint-owned файлов).

## 28. Live validation (§67)

Только READ_ONLY / inspect / dry-run: `hermes sbl status`,
`hermes sbl inspect-path <path>`, `hermes sbl inspect-command "<cmd>"`
(только classification, НЕ execute). Метрики: SYSTEM_MUTATION_
EXECUTED = 0, SELF_RESTART_EXECUTED = 0, BOUNDARY_BYPASS = 0.

## 29. CLI (§68)

`hermes sbl status` · `inspect` · `inspect-path` · `inspect-command`
· `graph` · `deps` · `refresh` — все read-only. В Sprint 1.3.3
запрещены: execute / apply / repair / restart / rollback / write /
delete.

## 30. Operator procedure

1. Проверить статус: `python -m agent.system_boundary.cli status`
   (mode, boundary_version, graph health).
2. Классифицировать подозрительную команду:
   `python -m agent.system_boundary.cli inspect-command "..."` —
   verdict/reason без выполнения.
3. Классифицировать путь:
   `python -m agent.system_boundary.cli inspect-path <path>`.
4. Мониторить метрики sbl_* (telemetry.snapshot()).
5. Для активации enforce: `HERMES_SBL_V2_MODE=enforce`.

## 31. Rollback

Single switch: `HERMES_SBL_V2_ENABLED=false` (или canonical project
equivalent). Возврат к Sprint 1.3.2 path (NoopSystemBoundary) после
внешнего operator restart. No DB rollback, no data loss.

## 32. Definition of Done — verified

- [x] CapabilityPolicyEngine — sole policy authority
- [x] VerifiedToolExecutor — sole execution gateway
- [x] VerifiedToolRegistry — sole execution registry
- [x] NoopSystemBoundary заменён реальным SBL
- [x] нет второго executor / duplicate receipt/idempotency
- [x] production authority не расширена
- [x] resource/operation/effective-action классификаторы детерминированы
- [x] indirect execution поддержан
- [x] traversal / symlink escape / parent symlink escape защищены
- [x] TOCTOU детектируется
- [x] gateway не может restart/kill себя (включая indirect)
- [x] service actions классифицированы; systemctl mutation не прячется за shell
- [x] bounded graph + provenance + trust classes + health + TTL
- [x] incomplete graph != empty graph; learned/inferred не доказывают safety
- [x] blast radius детерминирован, bounded, cycle-safe; UNKNOWN != NONE
- [x] risk_after >= risk_before
- [x] preflight tool/capability/operation/target/args/fingerprint-bound,
      expiring, replay protected
- [x] exception cannot PASS; BLOCK/REVALIDATE never reaches adapter
- [x] bypass невозможен через production V2 path
- [x] prompt/skill/plugin/MCP не могут обойти или grant trust
- [x] secret leakage = 0
- [x] STATUS_READ 100%, SEARCH_READ 100%, negatives unchanged
- [x] unsafe V2 = 0, system mutation executed = 0, self restart = 0
- [x] gateway stable, scheduler/provider unchanged, Telegram/MCP healthy
- [x] targeted/canonical/offline green; new regressions = 0
- [x] DB integrity green; perf gates met
- [x] backup verified, rollback ready, codemap current, git provenance recorded

## 33. Next

**SPRINT 1.3.4 — TRANSACTIONAL SYSTEM CHANGE PIPELINE**:
preflight → backup → execute → validate → health check → commit →
rollback on failure. (Не начинать без явной команды.)
