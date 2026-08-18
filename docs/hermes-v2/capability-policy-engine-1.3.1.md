# Capability Policy Engine — Sprint 1.3.1 (HARDENING)

> Спринт: 1.3.1 · Статус: PASS — CAPABILITY POLICY ENGINE HARDENED
> Дата: 2026-08-14 · Предшественник: Sprint 1.3.0 (CAPABILITY ROUTER V2 FOUNDATION)

## 1. Цель

Сделать `CapabilityPolicyEngine` единым, строгим и доказуемым
safety-layer для всех V2-решений. Новые production capabilities НЕ
добавляются, authority НЕ расширяется. Sprint 1.3.1 — хардненинг
модели решений, таксономии причин и fail-closed гарантий поверх
стабильного 1.3.0.

## 2. Модель решения — PolicyDecision (§1)

`CapabilityPolicyEngine.evaluate(...)` теперь возвращает канонический
`PolicyDecision` вместо кортежа `(verdict, reason)`:

| Поле | Тип | Обязательное |
|---|---|---|
| `route` | V2 \| LEGACY \| DENY | ✓ |
| `reason_code` | канонический ReasonCode (None при ALLOW) | ✓ |
| `risk_class` | RiskClass (effective risk §4) | ✓ |
| `capability` | str \| None | ✓ |
| `tool` | str \| None | ✓ |
| `rollout_mode` | off\|shadow\|canary\|limited_enforce\|enforce (§9) | ✓ |
| `health_state` | HEALTHY\|DEGRADED\|UNHEALTHY\|UNKNOWN (§6/§7) | ✓ |
| `confidence` | float \| None | ✓ |
| `policy_version` | `cap-policy-v1` (§10) | ✓ |
| `evaluated_checks` | bounded trace (§22) | опционально |

`route` DENY зарезервирован (§22 document-only) — в 1.3.1 ни один отказ
не уходит в DENY, все fail-closed → LEGACY (эквивалентность 1.2.4
байт-в-байт).

## 3. Каноническая таксономия причин — ReasonCode (§2)

Все deny/block причины — канонические коды, никакого free-text как
первичного ключа решения:

```
UNSAFE_INTENT  MIXED_UNSAFE_INTENT  CAPABILITY_UNSUPPORTED
CAPABILITY_UNVERIFIED  TOOL_UNVERIFIED  TOOL_RISK_MISMATCH
NETWORK_NOT_ALLOWED  APPROVAL_REQUIRED  HEALTH_UNAVAILABLE
LOW_CONFIDENCE  AMBIGUOUS_INTENT  ROLLOUT_DISABLED
SOURCE_NOT_ALLOWED  SECRET_QUERY  FILESYSTEM_NOT_ALLOWED
WEB_NOT_ALLOWED  POLICY_INTERNAL_ERROR
```

Плюс capability-specific гейт-коды verified-контрактов 1.2.x
(нормализованные, не free-text): `ALLOWLIST_MISS`,
`SUBTYPE_NOT_ALLOWED`, `QUERY_INVALID`, `ROLLOUT_LIMIT`.

`PolicyReason` остаётся legacy-алиасом класса с каноническими
значениями — старые импорты/тесты не ломаются, семантические решения
совпадают (эквивалентность §26).

## 4. Строгая лестница приоритетов (§3)

Первая терминальная причина побеждает:

1. `UNSAFE_INTENT`
2. `MIXED_UNSAFE_INTENT` (SEARCH-поверхность; §14 unsafe side first)
3. forbidden class: `SECRET_QUERY` / `FILESYSTEM_NOT_ALLOWED` /
   `WEB_NOT_ALLOWED`
4. `CAPABILITY_UNSUPPORTED`
5. `CAPABILITY_UNVERIFIED` / `TOOL_UNVERIFIED`
6. `TOOL_RISK_MISMATCH` (risk mismatch / effective risk)
7. `NETWORK_NOT_ALLOWED`
8. `APPROVAL_REQUIRED`
9. `HEALTH_UNAVAILABLE`
10. `LOW_CONFIDENCE` / `AMBIGUOUS_INTENT`
11. `ROLLOUT_DISABLED` / `ROLLOUT_LIMIT` (rollout policy — оценивается
    последним, перед ALLOW)
12. ALLOW_V2

STATUS_READ остаётся rollout-free (preserve 1.3.0/1.2.4: гейт rollout
применяется только к SEARCH-поверхности); S1-S7 эквивалентность 100%.

## 5. Effective risk (§4/§5)

```
effective = max(intent_risk, capability_risk, tool_risk, context_risk)
```

- Никогда не понижается (no downgrade).
- `intent_risk` — из классификатора (expected side effect), не
  понижается tool-метаданными (§26).
- `tool_risk` — из verified-контракта (авторитетен для execution risk,
  §16); missing/unknown метаданные → `TOOL_UNVERIFIED`.
- `context_risk` — контекстный риск вызова (по умолчанию READ_ONLY).
- Классы: READ_ONLY / REVERSIBLE_WRITE / IRREVERSIBLE_WRITE /
  SYSTEM_CONTROL / SECRET_ACCESS / UNKNOWN. Production V2 — READ_ONLY
  только.

## 6. Health gate + TTL (§6/§7)

- Дескриптор объявляет `health_requirement`: `HEALTHY` (default для
  production read) | `DEGRADED_ALLOWED` | `NO_HEALTH_REQUIREMENT`.
- Неизвестный/unavailable health → `HEALTH_UNAVAILABLE` (fail closed,
  никогда не маршрутизируется V2 оптимистично).
- Кэш-снапшоты несут bounded TTL (`health_ttl`, default 30s) с
  monotonic `fetched_at`: истёкший снапшот → UNKNOWN (никогда
  stale-ok); битая метка времени → UNKNOWN (fail closed).
- `normalize_health_snapshot(snapshot, ttl)` — единственная точка
  нормализации, используется и в evaluate, и в fail-путях.

## 7. Fail closed (§8/§19)

Любое из: исключение, missing metadata, unknown enum, invalid
descriptor, unknown rollout mode → LEGACY (или DENY). **Никогда ALLOW.**

`evaluate()` никогда не бросает: весь путь обёрнут в try/except, а
абсолютный fallback `_policy_error()` не трогает descriptor/health
(источники исключения) — только безопасные поля контекста →
`POLICY_INTERNAL_ERROR`, LEGACY. Метрика `policy_fail_closed` растёт.

## 8. Rollout-нормализация (§9)

`parse_rollout_mode()`: `off | shadow | canary | limited_enforce |
enforce`; unknown/None → `off` (fail closed). Значение попадает в
каждое `PolicyDecision.rollout_mode` и в телеметрию.

## 9. Версионирование политики (§10)

`POLICY_VERSION = "cap-policy-v1"` — в каждом решении и в метриках
(`by_policy_version`).

## 10. Метрики (§20)

`CapabilityRouterStats` расширен каноническими именами:
`policy_decisions_total`, `policy_allow_v2`, `policy_legacy`,
`policy_deny`, `policy_fail_closed`, breakdown `by_policy_version`,
`by_reason` (канонические коды). Секция `policy` в `to_dict()`.

## 11. Decision trace (§22)

`PolicyDecision.evaluated_checks` — bounded список пар
(проверка → исход): `unsafe=false, capability_verified=true,
health=HEALTHY, rollout=limited_enforce, ...`. Только нормализованные
значения, никаких raw prompt/tool args/секретов (§21).

## 12. Эквивалентность и тесты (§23-§26)

- **Precedence (§23)**: unsafe beats rollout, unsafe beats health,
  secret beats verified tool, risk mismatch beats health, health beats
  rollout, rollout evaluated last — 6 тестов.
- **Fail closed (§24)**: unknown risk / unknown capability / unknown
  tool / missing descriptor (None → POLICY_INTERNAL_ERROR) / exception
  in policy / unknown rollout / invalid confidence (включая NaN) →
  не V2 — 8 тестов.
- **Negative matrix (§13)**: явная таблица intent_risk × tool_risk ×
  capability_verified × health × rollout (STATUS) + SEARCH-матрица
  (text × subtype × health × rollout) — 16+6 кейсов, без неявных.
- **Property tests (§25)**: исчерпывающий itertools-sweep
  risk × side_effect × health × verified × rollout × confidence
  (4×5×5×2×6×4 = 4800 комбинаций) + search-свойство. Инвариант: ни
  одна комбинация с unsafe-условием не даёт ALLOW_V2. Фреймворк
  hypothesis недоступен — детерминированный полный перебор.
- **Health TTL (§7)**: expired → UNKNOWN → HEALTH_UNAVAILABLE; fresh →
  ok; malformed timestamp → fail closed.
- **Equivalence (§26)**: S1-S7 + P1-P12 + N1-N8 через IntentRouter —
  route/tool match 100% (canonical runner, 164 capability/search
  теста + 399 intent_router + 547 V2-scope), offline dataset 457/457
  accuracy 1.0, live 27/27 (см. §13).

## 13. Live-валидация (§29)

После одного контролируемого рестарта gateway (MainPID
293679 → 302652, NRestarts=0) — 27 live-проб через API:

| Сет | Кейсы | Результат |
|---|---|---|
| S1-S7 (STATUS_READ) | 7 | V2, per-subtype tool, match 100% |
| P1-P12 (SEARCH allowlist) | 12 | V2 `operational_log_search`, match 100% |
| N1-N8 (unsafe/не-allowlist) | 8 | LEGACY, канонические коды (CAPABILITY_UNSUPPORTED ×5, ALLOWLIST_MISS ×2, SECRET_QUERY ×1) |

`match_route=True match_tool=True match_reason=True` на всех 27
(пост-рестарт enforce-строки). unsafe V2 = 0. Ошибок/исключений в
gateway за окно: 0.

## 14. Активация / Rollback (§36)

- Активация: существующий drop-in
  `sprint130-capability-router.conf` (`HERMES_CAPABILITY_ROUTER_V2=
  enforce`) — флаг не менялся; один контролируемый рестарт.
- **Rollback (1.3.1)**: `HERMES_CAPABILITY_ROUTER_V2=false` (или
  удалить drop-in) + рестарт → мгновенный возврат к Sprint 1.3.0
  поведению (STATUS_READ/SEARCH_READ enforcement при этом независимы
  и не отключаются). Новый policy-слой отключается фича-флагом,
  schema/DB не затронуты.

## 15. Секьюрити-аудит (§21/§46)

- Никаких raw prompt / tool args / secrets / config values в
  решениях, метриках, логах — только нормализованные коды.
- No arbitrary tool discovery: registry статический, конструктор
  валидирует против verified-контрактов.
- No shell/network от роутера: resolver/policy — чистый Python, без
  I/O (policy pure function §18).
- No capability escalation: effective risk = max, intent не понижается.
- unsafe V2 = 0 по построению + доказано live.
- Policy exceptions никогда не ALLOW (доказано инжекцией §19/§24).

## 16. Результаты спринта

- Изменён модуль: `agent/capability_router/` (models, policy, flags,
  registry, metrics, router, capabilities, `__init__`) — PolicyDecision,
  ReasonCode, health gate+TTL, rollout-нормализация, fail-closed
  fallback, policy-метрики.
- Тесты: обновлён `test_capability_policy.py` (contract update на
  PolicyDecision/канонические коды, +8 новых), новый
  `test_capability_policy_matrix.py` (29 тестов: матрица, fail-closed,
  property, TTL).
- Scope: intent_router 399/399 (1 environmental — /tmp/hgw_reload
  артефакты живого gateway; 13/13 после карантина), V2-scope
  547/547, offline 457/457 (accuracy 1.0).
- Perf: policy p95 **0.05 ms** (<1 ms), router p95 **0.068 ms**
  (<5 ms).
- DB: integrity ok, WAL, без изменений схемы.
- Документация: этот файл + обновлены capability-router-1.3.0.md,
  operator-runbook.md, production-activation.md,
  intent-router-evaluation.md.

## 17. Дальше

- **Sprint 1.3.2 — VERIFIED TOOL EXECUTION CONTRACT** (по брифу).
  Не начинать автоматически.
