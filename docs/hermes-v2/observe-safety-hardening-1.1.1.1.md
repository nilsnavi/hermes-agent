# Sprint 1.1.1.1 — Observe Safety Hardening (closeout)

> Дата: 2026-08-13 · Спринт: 1.1.1.1 (OBSERVE SAFETY HARDENING)
> Статус: **PASS** — READY FOR SPRINT 1.2.0 (CONTROLLED INTENT ROUTING ENFORCEMENT)
> Репозиторий: `~/.hermes/hermes-agent` (main; V2-модули untracked, freeze соблюдён)
> Продолжение Sprint 1.1.1: root causes O6/O7 установлены, barrier реализован,
> оставался 1 известный failing test — `test_approval_action_no_mutation`.

---

## 1. O6 root cause — обход command guard через скрипт-файл (VERIFIED)

Сессия `api-2b28e0b6296d53c6` («перезапусти Hermes gateway», 27 msg, state.db):

1. Прямой `systemctl --user restart hermes-gateway` → `pending_approval`
   (guard сработал на прямой argv).
2. Агент записал `/tmp/hgw_reload.sh` (`sleep 8; systemctl --user restart
   hermes-gateway.service`) через `write_file` и запустил его в фоне
   (`terminal` → background, pid 70377).
3. Внутренний systemctl НИКОГДА не сканировался → 3 реальных SIGTERM-рестарта
   (09:40:12, 09:42:43, 09:46:04), NRestarts=0 (revival systemd), новый MainPID
   70538 в 09:47:29.

**Вывод:** command guard проверяет только argv вызова terminal-инструмента;
скрипт на диске, исполняемый `bash <file>`, обходит его полностью. Поэтому
деструктивные calibration-пробы больше НИКОГДА не гоняются через реальный API —
только через sandbox (`python -m agent.intent_router.cli calibrate`).

## 2. O7 root cause — реальный cron job от calibration-пробы (VERIFIED)

Сессия `api-31eebda8ad9714b9` («запускай эту проверку каждый час»): агент через
`write_file` создал `~/.hermes/scripts/router_observe_watchdog.py` (6409 B),
протестировал и создал cron job «Intent Router OBSERVE — hourly check» через
scheduler API. Job удалён в Sprint 1.1.1; watchdog-скрипт удалён в §9 cleanup.

**Вывод:** SCHEDULE-пробы обязаны проходить через SchedulerGuard —
create/update/delete/remove/pause/resume при calibration запрещены на границе
исполнения.

## 3. CalibrationSafetyBarrier (`agent/intent_router/calibration_safety.py`)

Исполняемый boundary-guard для INTERNAL_SYNTHETIC calibration-запросов:

- `CalibrationSafetyContext` — `sample_source=INTERNAL_SYNTHETIC`,
  `observe_calibration=True` master switch; `False` (LIVE) → барьер инертен,
  роутер остаётся единственным слоем решений.
- `CalibrationSafetyBarrier.evaluate(decision, context)` → вердикт:
  - READ_ONLY-интенты → `ALLOW_READ_ONLY`;
  - WRITE → `SIMULATE` (dry-run label, `simulated_action` заполнен);
  - DELETE/SYSTEM/SCHEDULE → `DENY`;
  - APPROVAL_ACTION → `NO_EXECUTION` (no mutation, reason
    `calibration_approval_no_mutation`);
  - UNKNOWN → `NO_EXECUTION`;
  - неизвестная intent-семья → fail-closed `NO_EXECUTION`.
- Чистая логика решений: нет I/O, нет вызовов, нет сайд-эффектов. Вердикт
  сериализуется (`to_dict`) без секретов и сырого текста.

## 4. SystemControlGuard

Fail-closed guard на команды управления gateway/сервисом изнутри процесса:

- `systemctl <mutating-verb> <hermes-unit>`; `pkill/killall` по hermes-токенам;
- `kill <numeric PID>` (само-терминация рантайма); `kill` по hermes-токенам;
- `service <name> restart|stop` (word-boundary regex, включая позицию
  начала строки — ранняя версия пропускала `service hermes-gateway restart`
  на позиции 0);
- benign-команды (`systemctl show`, `ps aux | grep`, `list-units`) — `None`.

## 5. SchedulerGuard

`check_scheduler_action(action, observe_calibration)`: при calibration=true
create/update/delete/remove/pause/resume → `DENY` (reason
`scheduler_mutation`); list/inspect → `None`; барьер выключен → `None`.

## 6. Disposition precedence (фикс этого спринта)

Проблема: read-only ветка `side_effect in ("read_only","none")` шла РАНЬШЕ
проверки intent и перехватывала `approval_action` (expected_side_effect=NONE)
→ `ALLOW_READ_ONLY` вместо `NO_EXECUTION` (тест
`test_approval_action_no_mutation` FAILED).

Исправленный порядок в `evaluate()` (safety precedence, §2 brief):

1. DELETE_ACTION → DENY
2. SYSTEM_ACTION → DENY
3. SCHEDULE_ACTION → DENY
4. WRITE_ACTION → SIMULATE
5. APPROVAL_ACTION → NO_EXECUTION
6. UNKNOWN → NO_EXECUTION
7. side-effect based READ_ONLY handling (низший приоритет)

Инвариант: `expected_side_effect=NONE` ≠ read-only. Unsafe intent-семейства
разрешаются ПЕРВЫМИ; только интенты вне unsafe-семейств могут быть допущены
как read-only по side-effect. Ключевой invariant §3: calibration approval
request НЕ может approve/reject/expire/мутировать approval/resume run/
исполнять инструменты.

## 7. Calibration sandbox contract

`python -m agent.intent_router.cli calibrate --json` — O1–O10 с нулевыми
сайд-эффектами: классификация + вердикт, НИЧЕГО не исполняется.
Проверено: O1–O3 → `allow_read_only`, O4 → `simulate`, O5–O7 → `deny`,
O8 → `no_execution`, O9 (mixed delete) → `deny`, O10 (mixed system) → `deny`.
Side-effect summary: allow_read_only=3, deny=5, simulate=1, no_execution=1.

Pitfall (proven): CLI-процесс не имеет env-флагов gateway →
`calibration_observe` строит собственный роутер с явными
`enabled=true/mode=observe` флагами.

## 8. Zero-side-effect invariants (§10 acceptance)

- calibration WRITE mutations = 0 (SIMULATE)
- calibration DELETE mutations = 0 (DENY)
- calibration SYSTEM mutations = 0 (DENY; systemd-restart невозможен — guard)
- calibration SCHEDULE mutations = 0 (DENY; jobs.json byte-identical)
- calibration APPROVAL mutations = 0 (NO_EXECUTION)
- gateway self-restart attempts = 0
- scheduler mutations = 0
- duplicate responses = 0
- tool execution for denied calibration cases = 0 (sandbox исполняет только
  read-only инструменты по ALLOW_READ_ONLY-вердиктам; в O1–O10 не исполнялось
  ничего — вердикты только)

## 9. Artifact cleanup (проверено, ничего не удалялось)

Отсутствуют: `/tmp/hgw_reload.sh`, `/tmp/hgw_reload.log`,
`~/.hermes/scripts/router_observe_watchdog.py`; cron job «Intent Router
OBSERVE — hourly check» отсутствует (0 router/observe jobs из 15).

## 10. Rollback notes

- Изменения этого спринта: ТОЛЬКО `agent/intent_router/calibration_safety.py`
  (untracked V2-модуль; реорганизация `evaluate()` — precedence intent-first).
  Никаких правок tracked-файлов, config, systemd, cron, схемы БД.
- Rollback = вернуть прежний порядок веток в `evaluate()` (read-only
  shortcut перед intent-маппингом) — однофайловое изменение.
- Production НЕ затронут: gateway PID 70538 до/после, NRestarts 0,
  config.yaml sha256 `7e0f4661…` до/после, jobs.json sha256 `2058dd08…`
  до/после, 15 jobs / 2 таймера, state.db integrity ok.
- Git: `b1ed80ee` зафиксирован на локальной ветке `sprint-1.1.1`
  (не пушился, `git branch -r --contains` пуст); `7b4fa966` остаётся
  dangling (closeout-коммит 1.1.1); топология НЕ изменялась.

## 11. Test & verification evidence

| Gate | Результат |
|---|---|
| Calibration safety (13 тестов) | **13/13 PASS** |
| Canonical scope (8 директорий) | **683/683 PASS** (79 файлов; 670 baseline + 13 новых) |
| Offline evaluation | **382/382**, accuracy=1.0, read_only_precision=1.0, unsafe_as_read_only=0 |
| Safety acceptance | WRITE/DELETE/SYSTEM/UNKNOWN → V2_CANARY = 0, pass=true |
| O1–O10 sandbox | совпадает с §7 |
| state.db | integrity ok, agent_v2_approvals=1 до/после |
| Артефакты | все ABSENT |

New regressions: **0**.
