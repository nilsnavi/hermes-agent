# STATUS_READ Enforcement — Sprint 1.2.0

Дата: 2026-08-13 · Тип: controlled production routing enforcement (first)
Кратко: **впервые** Intent Router влияет на реальный production routing —
только для строго ограниченного безопасного класса STATUS_READ.

## 1. Что разрешено (scope enforcement, §1)

Automatic V2 routing разрешён ТОЛЬКО если выполняется КАЖДЫЙ гейт:

| Гейт | Условие |
|---|---|
| intent | `STATUS_READ` (allowed_intents = {STATUS_READ}) |
| risk | read-only grade (`LOW`) |
| expected_side_effect | `NONE` или `READ_ONLY` |
| capabilities | полностью verified (`READ_RUNTIME_STATUS`) |
| provider/runtime health | `HEALTHY` |
| allowlist | текст проходит STATUS_READ allowlist (§7) |
| approval | не требуется |
| ambiguity | отсутствует (defensive: lexical_hits != [ambiguous]) |
| confidence | >= 0.7 |
| policy | EnforcementPolicy.enabled |

Иначе: **LEGACY** (fail closed, §6).

## 2. Запрещено (никогда не направлять в V2)

SEARCH_READ, CONVERSATION, WRITE_ACTION, DELETE_ACTION, SYSTEM_ACTION,
SCHEDULE_ACTION, APPROVAL_ACTION, UNKNOWN, mixed intent, low-confidence
intent. Не включены: percentage rollout, autonomous planner, write tools,
scheduler execution, system control, provider switching, LLM-based classifier.

## 3. Режим (feature flag, §3)

```
HERMES_INTENT_ROUTER_ENABLED=true          (общий мастер, observe drop-in)
HERMES_INTENT_ROUTER_MODE=enforce_status_read
```

Allowed production modes: `off` | `observe` | `enforce_status_read`.
Любое другое значение (включая `enforce`, `shadow_decision`, мусор) →
fail closed to `off` (`parse_mode`). Default: off.

## 4. EnforcementPolicy (§4)

Новый модуль `agent/intent_router/enforcement.py`:

| Поле | Default |
|---|---|
| enabled | True |
| allowed_intents | {STATUS_READ} |
| min_confidence | 0.7 |
| require_health | True |
| require_capabilities | True |
| require_internal_allowlist | True |
| fallback_route | LEGACY |

`EnforcementPolicy.evaluate(classification, text, health)` — чистая функция:
intent-family гейт ПЕРВЫМ (доказанный порядок disposition из 1.1.1.1 —
unsafe intent с `side_effect=NONE` не может попасть в read-only ветку),
затем risk → side_effect → confidence → capability → health → allowlist →
approval/ambiguity (defensive). Возвращает (allowed, block_reason, reasons).

## 5. STATUS_READ allowlist (§7)

Минимальный, НЕ расширяется автоматически (5 фраз, word-boundary match по
нормализованному тексту):

```
покажи статус hermes | статус gateway | состояние сервиса | health hermes | gateway status
```

E3 («найди статус последнего деплоя», search_read) НЕ проходит — нет фразы.

## 6. Verified tool surface (§8)

`runtime_status` (primary) + `canary_ping` — фактический текущий безопасный
registry (READ_ONLY, local-only, без внешних endpoint'ов, bounded timeouts).
Enforced run выполняет **максимум ОДИН** verified tool (§19); write/unknown
tools невидимы (SafeCanaryToolRegistry → INVALID_PLAN → 0 execution).

## 7. Gateway authority (§5) и exactly-one-response (§9/§10)

```
legacy_decision = current routing
router_decision  = IntentRouter.enforce(features, text)
if enforcement policy allows: actual_route = V2_CANARY (canary path, safe registry)
else:                         actual_route = legacy_decision
```

- V2 route → legacy response path НЕ выполняется (early return, exactly one).
- Fallback to legacy ТОЛЬКО до side effect: `ok=False` +
  `fallback_allowed=True` → legacy; после TOOL_STARTED (`fallback_allowed=False`)
  → controlled message, никогда legacy (§30 invariant).
- `adapter.enforce_event(event, step_specs, allow_production=True)` — тот же
  поверх, что canary_event, но authority от Router (не metadata opt-in).
- Hooked: `gateway/run.py::_handle_message` (legacy platforms) +
  `gateway/platforms/api_server.py::_run` (API-server path).

## 8. Наблюдаемость (§11)

Счётчики (RouterStats.enforcement, in-memory, per-process):
attempts / allowed / blocked / fallback / success / failure / unsafe +
`enforcement_blocks` по block_reason:
INTENT_NOT_ALLOWED, LOW_CONFIDENCE, HEALTH, CAPABILITY, ALLOWLIST,
APPROVAL, AMBIGUOUS, POLICY, ROUTER_ERROR.

Лог-строка: `gateway.intent_router.enforce request_id=… intent=… allowed=…
route=… block_reason=… reasons=… eligible_tools=… confidence=…
duration_ms=… sample=… policy=…` (whitelisted scalars, без prompt/args).

## 9. Safety metrics (§12) — критично

WRITE/DELETE/SYSTEM/SCHEDULE/APPROVAL/UNKNOWN routed V2 = **0**.
`enforcement.unsafe` > 0 → `health() == UNHEALTHY` (§12 trigger) → FAIL +
auto-disable enforcement. По конструкции = 0: intent-гейт первый.

## 10. Авто-disable (§29)

Немедленно отключить enforcement (MODE=observe) если: unsafe routed V2 > 0,
duplicate response, duplicate tool call, router exception влияет на запрос,
V2 STATUS_READ failure rate > 5%, gateway instability, SQLite lock regression,
secret leakage, unexpected scheduler/provider/system mutation.

## 11. CLI

```
python -m agent.intent_router.cli enforce --text "покажи статус Hermes" [--force] [--json]
python -m agent.intent_router.cli enforce-suite [--json]      # E1–E10 (§16/§17)
```

`--force` = sandbox (env-independent, healthy stub) — CLI-процесс без
gateway-флагов, live health probe там unknown by design.

## 12. Controlled cases E1–E10 (§16)

| Case | Text | Expected | Actual (suite) |
|---|---|---|---|
| E1 | покажи статус Hermes | V2_CANARY | V2_CANARY |
| E2 | gateway status | V2_CANARY | V2_CANARY |
| E3 | найди статус последнего деплоя | LEGACY | LEGACY |
| E4 | привет | LEGACY | LEGACY |
| E5 | отправь сообщение | LEGACY | LEGACY |
| E6 | удали лог | LEGACY | LEGACY |
| E7 | перезапусти gateway | LEGACY | LEGACY |
| E8 | каждый час проверяй статус | LEGACY | LEGACY |
| E9 | сделай это | LEGACY | LEGACY |
| E10 | проверь статус и перезапусти сервис | LEGACY | LEGACY |

10/10 PASS; unsafe_enforced=0 (6 unsafe intents учтены как blocked).

## 13. Тесты (§15) — tests/intent_router/test_enforcement.py

26 тестов: 15 обязательных + §3 mode-parse fail-closed + §12 safety
counters + allowlist exactness. Router-level (без исполнения) + adapter-level
(no-double-tool-execution на throwaway temp DB).

## 14. Офлайн-оценка (§25)

382/382, accuracy=1.0, read_only_precision=1.0, unsafe_as_read_only=0,
unsafe_as_canary=0. Классификатор/правила НЕ менялись (additive-only).

## 15. Rollback (§28)

```
HERMES_INTENT_ROUTER_MODE=observe   # или HERMES_INTENT_ROUTER_ENABLED=false
```
+ controlled external gateway restart. DB-rollback не нужен (enforcement
пишет только telemetry/run journal в agent_v2_*).

## 16. Sample limit (§21)

Max 20 enforced live STATUS_READ за initial validation window; после 20 —
mode остаётся enabled только если all green.

## 17. Live activation evidence (2026-08-13)

Активация: drop-in `sprint112-enforce.conf` (ENABLED=true,
MODE=enforce_status_read) + controlled external restart (§18):
70538 → 143116 → (health-probe fix) 144022 → (NameError fix + durable DB)
145623 → 145986 → 145175. Все рестарты плановые: NRestarts=0,
ExecMainStatus=0. Флаги подтверждены в /proc/<PID>/environ.

Активационные правки (обнаружены в E1-drill, каждая с регрессионным тестом):

1. **`_pid_health` vs JSON pid-файл** — gateway.pid теперь JSON
   (`{"pid": N, ...}`), старая проба ожидала голое число → status=unknown
   → HEALTH-блок (fail closed, корректно, но блокировало E1). Fix:
   `_parse_pid_file` (JSON + int) + `test_pid_health_parses_json_and_plain_pid_file`.
2. **Class-body NameError в api_server** — `session_id = session_id or ""`
   внутри class-тела `_EnforceEvent` → NameError (class-scope делает имя
   локальным). Fix: предвычисление значений до class. Fail-open сработал
   штатно (legacy, один ответ, без дублей).
3. **Durable run journal** — enforce_event писал в throwaway temp-DB;
   hook теперь передаёт `db_path=<HERMES_HOME>/state.db` (как canary-suite).

Первый live enforced запрос (§19) — «покажи статус Hermes»:

```
gateway.intent_router.enforce request_id=api-… intent=status_read
  allowed=True route=V2_CANARY block_reason=None
  reasons=status_read_enforced eligible_tools=runtime_status,canary_ping
  confidence=0.9 duration_ms=0.331 sample=LIVE policy=enforcement-v1
gateway.v2.enforce.result ok=True code=V2_OK fb=False tools=1
```

- HTTP 200 за **1.47 s** (legacy-базовый ответ 20–45 s) — latency ok (§23);
- ровно 1 verified read-only tool (runtime_status), 1 ответ, без legacy-дубля;
- DB side effect = только telemetry/run journal: runs 10→11
  (`run_20260813130008628223_1`, chat, completed), events 120→132,
  orphans=0, duplicates=0.

Негативные live-прогоны (§20) — E3–E10 все `allowed=False route=LEGACY`
(INTENT_NOT_ALLOWED): search_read, conversation, write_action,
delete_action, system_action ×2, schedule_action. Safety §12:
WRITE/DELETE/SYSTEM/SCHEDULE/APPROVAL/UNKNOWN routed V2 = **0**.

Stability window (§22) начат после финального рестарта; чекпоинты см.
`/tmp/sprint112-checkpoints.jsonl` (PID, RSS, threads, FDs, enforce-счётчики,
SQLite locks, Telegram/MCP, DB integrity).

## 18. Full regression — failure classification (2026-08-13)

Полная регрессия: **31623 passed / 11 failed / 210 skipped** (~22.5 min).
Канонический гейт (8 директорий): **709/709** в первом прогоне; во втором
710/710 после изолированной классификации. Классификация всех фейлов —
environmental / pre-existing, **новых V2-регрессий 0** (ни один файл не
импортирует изменённые модули; все файлы git-clean):

| Тест | Класс | Доказательство |
|---|---|---|
| test_turn_lease (timeout hook) | timing flake | изолированно PASS |
| test_plugins.py / plugin_scanner / cmd_category_discovery ×4 | rtk-hermes plugin env (известный, 1.0.6.3) | env-зависимый discovery |
| test_qwen_oauth_auto_fallthrough | auth-pool env (известный, 0.11) | live `~/.hermes/auth.json` содержит qwen-oauth |
| test_setup_openclaw_migration | plugin env | live plugins регистрируются в discovery |
| test_live_system_guard_self_test ×3 | live-host guard | guard защищает ЖИВОЙ gateway; text-скан агрессивнее на live-хосте |
| test_hermes_state FTS5 projection | host-state | query-count assertion, без связи с V2 |
| test_scheduler_unchanged_after_schedule_probe | **live-host артефакт от E7-пробы** | `/tmp/hgw_reload.sh` создан legacy-агентом при перезапуске gateway (16:00:52); после очистки PASS |

Урок (в runbook): system/destructive live-пробы (E7 «перезапусти gateway»)
выполняются legacy-агентом реально — слать ПОСЛЕДНИМИ и проверять gateway
после; параллельно с ними тестовую регрессию не гонять (артефакты в /tmp
ломают калибровочные safety-тесты).
