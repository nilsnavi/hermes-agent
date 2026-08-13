# SELF_IMPROVEMENT_POLICY.md

Политика самосовершенствования Hermes Agent (инстанс Эдварда, Proxmox LXC).
Зафиксирована в Sprint 0.11. Цель — управляемая, верифицируемая эволюция
вместо дрейфа: каждое изменение обязано быть до/после-проверяемым, а не
«полагаемым».

## 1. Три правила

1. **Минимальное изменение.** Чинить причину, а не симптом; убивать
   legacy-слой целиком, если он коллизионен (пример: `_legacy_pattern_key`,
   удалён в Sprint 0.11 — точечный фикс оставил бы дыру).
2. **Верификация до фиксации.** Тест-покрытие изменённого модуля (scope =
   процент изменённых строк, покрытых тестами) обязано быть зелёным, прежде
   чем изменение попадает в baseline.
3. **Изоляция от runtime.** Изменения в live-системе — только после
   pre-change backup, через reversible-механизмы (drop-in override systemd,
   env-файлы 600, не правка единицы), с проверкой пост-состояния
   (PID/NRestarts/флаг в /proc).

## 2. Разрешено без согласования

- Исправление тестовой изоляции (tmp_path/фикстуры, mock `_permanent_approved`)
  — при условии, что тест остаётся строже прежнего.
- Документация, комментирование кода, пояснительные docstring'и.
- Обработка ложных срабатываний detection-пайплайна без потери threat-покрытия
  (пример Sprint 0.11: live-system guard — `echo "find -delete"` больше не
  триггерит approval, при этом `echo "$(find . -delete)"` и
  `echo 'find -delete' | xargs find` остаются заблокированными).
- Внешние API через единственный рабочий путь (SOCKS5 127.0.0.1:1080) —
  добавление `--socks5-hostname`/`--max-time` в скрипты-коллекторы.
- Non-destructive DB maintenance: `hermes sessions optimize` (FTS merge +
  VACUUM, no data change).

## 3. Требует процедуры (pre-change backup + review)

- Изменение `DANGEROUS_PATTERNS` / mechanisms approval-пайплайна.
- Изменение скиллов (`skill_manage`): SHA256 снимается ДО и ПОСЛЕ; baseline
  хэш перефиксируется только при осознанном изменении (см. §5).
- Изменение конфигов безопасности (approvals/security/провайдеры),
  network/firewall/Telegram/MCP/Assistant server.
- Включение разрушающих опций (например, `sessions.auto_prune: true`).
- Обновление пакетов/зависимостей.

## 4. Никогда (заморозка STABILIZATION)

Пока открыт спринт стабилизации: без явной команды пользователя не менять
primary provider / API keys / provider reauth, не делать git commit/push,
не создавать новые скиллы, не запускать self-improvement вручную, не
начинать Run Engine / Planner / Agent Registry.

## 5. Верификация скиллов

- Каждый спринт фиксирует `SHA256` всех SKILL.md в baseline-файле.
- Сверка: `sha256sum` по списку → diff против baseline → расхождения
  классифицируются: (a) осознанное изменение (документируется в changelog
  спринта), (b) дрейф (восстанавливается из baseline).
- Скилл считается «проверенным», если hash совпал с baseline И навык
  использовался в спринте без выявленных дефектов.

## 6. Откат

- Pre-change backup (`sprintNNN-prechange-<ts>/`) — до любого изменения кода:
  затронутые файлы + `db/state.db.snapshot` + SHA256SUMS (600, каталог 700).
- Restore rehearsal обязателен перед фиксацией STABLE-BASELINE.
- Rollback live-конфига — через удаление drop-in override + systemd daemon-reload
  (никакой правки основного unit).

## 7. Критерий закрытия спринта

`STABILIZATION CLOSED — READY FOR HERMES AGENT 2.0 CORE` выставляется
только при: полный suite зелёный (или задокументированные исключения),
live-валидация джобов ok=True, DB integrity ok + reclaim выполнен,
restore rehearsal пройден, readiness score ≥ 4.0/5.0.