# Capability Router V2 — Sprint 1.3.0 (FOUNDATION)

> Спринт: 1.3.0 · Статус: PASS — CAPABILITY ROUTER V2 FOUNDATION STABLE
> Дата: 2026-08-14 · Предшественник: Sprint 1.2.4 (SEARCH_READ limited production)

## 1. Цель

Единый слой маршрутизации, который принимает решение Intent Router
(intent + subtype) и выбирает **verified capability/tool** через registry +
policy:

```
Intent Router (classify → subtype)
     ↓
CapabilityResolver          intent/subtype → CapabilityRequirement
     ↓
CapabilityRegistry          статические verified descriptors (§27-валидация)
     ↓
CapabilityPolicyEngine      fail-closed лестница приоритетов (§9)
     ↓
CapabilityRouteDecision     V2 | LEGACY | DENY (+ tool, reason)
     ↓
Execution Adapter           gateway V2 canary path (НЕ изменён)
```

**Sprint 1.3.0 НЕ расширяет production authority**: набор V2-маршрутизируемых
интентов после спринта — ровно тот же, что в 1.2.4 (STATUS_READ по
per-subtype verified tools + SEARCH_READ по limited-production allowlist).
Всё остальное — LEGACY. Функциональная эквивалентность доказана:
оффлайн-датасет, canonical-тесты и live-валидация дают route/tool/reason
mismatch = 0.

## 2. Capability-модель (§2)

Шесть verified capability (никаких выдуманных):

| Capability | Канонический tool | Subtype (STATUS_READ) |
|---|---|---|
| `STATUS_RUNTIME` | `runtime_status` | runtime/service/health/generic |
| `STATUS_GATEWAY` | `gateway_status` | gateway |
| `STATUS_INTEGRATION` | `integration_status` | integration |
| `STATUS_SCHEDULER` | `scheduler_status` | scheduler |
| `STATUS_PROVIDER` | `provider_status` | provider |
| `OPERATIONAL_SEARCH` | `operational_log_search` | search_read (все 5 subtypes) |

- Per-request tool для HEALTH_STATUS = `health_status` (наследие контракта
  1.2.1 §4 — tool-эквивалентность точная); HEALTH/SERVICE/GENERIC сидят под
  `STATUS_RUNTIME`.
- `canary_ping` остаётся legacy fallback-поверхностью и НЕ является
  маршрутизируемым tool'ом в 1.3.0 (§5 «if still needed» → not needed).
- **Deny list (§22, document-only, без реализации)**: WRITE, DELETE,
  SYSTEM_CONTROL, SCHEDULE_MUTATION, APPROVAL_WRITE, FILESYSTEM_SEARCH,
  WEB_SEARCH, SECRET_ACCESS, ARBITRARY_DB, UNKNOWN.
- **Future placeholders (§23, verified=false, routable=false)**:
  MESSAGE_SEND, REMINDER_CREATE, FILE_READ, WEB_SEARCH, WORKFLOW_EXECUTION.

## 3. Компоненты

### agent/capability_router/

| Файл | Роль |
|---|---|
| `capabilities.py` | enum Capability/RiskClass/Route/Verdict + §24-§25 risk-модель (`max_risk`) |
| `models.py` | CapabilityRequirement (§3), CapabilityDescriptor (§4), CapabilityRouteDecision (§10), PolicyReason |
| `flags.py` | `HERMES_CAPABILITY_ROUTER_V2` (off\|shadow\|enforce; unknown → off) |
| `registry.py` | статический CapabilityRegistry + §27-валидация против verified-контрактов 1.2.x |
| `resolver.py` | детерминированный CapabilityResolver (no LLM/no network/no DB) |
| `policy.py` | CapabilityPolicyEngine — лестница §9, effective risk = max (§25), mismatch §26 |
| `metrics.py` | §29/§30 счётчики + bounded latency ring |
| `router.py` | оркестрация resolver→registry→policy→decision + shadow-сравнение + benchmark |

### Single source of truth (§6)

Метаданные безопасности tool'ов (side_effect/idempotent/network/approval) НЕ
дублируются: registry-дескрипторы валидируются против verified-таблиц
1.2.1/1.2.2 (`STATUS_TOOL_METADATA`, `SEARCH_TOOL_METADATA` в
`agent/intent_router/enforcement.py`) при конструировании — любое расхождение
(риск, network, неизвестный tool) → `RegistryValidationError` ДО маршрутизации.

## 4. Policy Engine (§8-§9) — fail-closed приоритеты

1. unsafe intent → LEGACY
2. mixed unsafe intent (SEARCH) → LEGACY
3. unsupported capability / unverified tool → LEGACY
4. side-effect violation (effective risk > READ_ONLY) → LEGACY
5. network violation → LEGACY
6. approval requirement → LEGACY
7. unhealthy dependency → LEGACY
8. confidence / ambiguity → LEGACY
9. rollout policy (search mode + 50-live cap) → LEGACY
10. capability-специфичные гейты (allowlist/subtype/source/query — порядок
    сохранён по verified-контракту 1.2.4) → LEGACY
11. ALLOW_V2

- **Effective risk = max(intent_risk, tool_risk, policy_risk)** — никогда min
  (§25). Descriptor не может понизить риск классификации.
- **Mismatch §26**: intent READ_ONLY + tool WRITE → LEGACY/DENY; intent WRITE
  + tool READ_ONLY → всё равно unsafe по intent.
- **DENY-маршрут существует, но в 1.3.0 НЕ срабатывает** (§22 document-only):
  каждый отказ fail-closed → LEGACY, байт-в-байт как 1.2.4. `denied = 0`.

## 5. Флаг и режимы (§15/§16)

`HERMES_CAPABILITY_ROUTER_V2` (default **false/off**, unknown → off):

| Режим | Поведение |
|---|---|
| `off` | инертно, нулевая нагрузка (production default) |
| `shadow` | решение вычисляется + сравнение с legacy (route/tool/reason/subtype), маршрут НЕ меняется |
| `enforce` | решение принимает Capability Router для ТОЧНОГО скоупа 1.2.4: STATUS_READ (все subtypes) + SEARCH_READ при `HERMES_SEARCH_READ_MODE=limited_enforce` |

Scope-гейт enforce: вне `status_read`/`search_read` и для search вне
`limited_enforce` решение остаётся за legacy-путём (canary/shadow/off
сохранены байт-в-байт). Любая ошибка capability router'а → fail closed к
legacy-исходу (поведение 1.2.4, §48).

## 6. Equivalence-доказательство (§13/§14/§30)

- Shadow-сравнение в каждом enforce-решении: `match_route`, `match_tool`,
  `match_reason`, `match_subtype` + агрегаты §30
  (`decision_match`/`route_mismatch`/`tool_mismatch`/`reason_mismatch`).
- Причины мапятся на legacy-коды (`legacy_reason_for`): POLICY_REASON →
  INTENT_NOT_ALLOWED/ALLOWLIST/SECRET_QUERY/... — сравнение like-for-like.
- Сравнение tool'ов: заблокированный маршрут = tool None с обеих сторон
  (legacy eligible_tools=[] на deny).
- Канонический корпус: S1-S7 (STATUS_READ по 7 subtypes), P1-P12 (prod
  allowlist), N1-N8 (unsafe/не-allowlist) — 100% route/tool/reason match.
- Оффлайн-датасет (§36) + canonical + live-валидация — см. финальный отчёт.

## 7. Наблюдаемость (§29)

- `IntentRouter.stats()["capability_router"]`: decisions/allowed/legacy/
  denied/errors, comparison (§30), by_intent/by_capability/by_tool/by_reason/
  by_route, duration p50/p95.
- `router.health()["capability_router"]`: mode + сводка.
- enforce-log строка: `cap_mode= cap_route= cap= cap_tool= cap_reason=
  match_route= match_tool= match_reason=`.
- `EnforcementOutcome.capability_*` / `match_*` поля (в to_dict тоже).

## 8. Performance (§31)

Бенчмарк 10,000 детерминированных резолюций (enforce-режим, healthy,
allowlisted STATUS_READ):

- resolver: p50 0.0004 ms, p95 0.0004 ms (< 1 ms gate)
- full router: p50 0.031 ms, p95 0.041 ms (< 5 ms gate)

## 9. Активация / Rollback (§39/§48)

- Активация: drop-in `~/.config/systemd/user/hermes-gateway.service.d/
  sprint130-capability-router.conf` с `HERMES_CAPABILITY_ROUTER_V2=enforce`
  + один контролируемый рестарт (§42).
- **Rollback**: установить `HERMES_CAPABILITY_ROUTER_V2=false` (или удалить
  drop-in) + рестарт gateway → маршрутизация STATUS_READ/SEARCH_READ
  мгновенно возвращается к Sprint 1.2.4 поведению. STATUS_READ enforcement
  и SEARCH_READ prod-mode при этом не отключаются (они независимы).

## 10. Секьюрити-аудит (§46)

- Нет утечки секретов: в решениях/метриках/логах нет raw prompt, auth,
  tool args.
- Нет arbitrary tool discovery: registry статический, конструктор
  валидирует против verified-контрактов.
- Нет shell/network от роутера: resolver/policy — чистый Python, без I/O.
- Нет capability escalation: effective risk = max, intent не понижается.
- Нет конфиг-мутаций: конфиг не трогали, только drop-in.
- unsafe V2 = 0 по построению (unsafe intents не резолвятся).

## 11. Результаты спринта

- Новый модуль: `agent/capability_router/` (8 файлов).
- Интеграция: `agent/intent_router/router.py` (флаги + enforce choke point +
  stats/health), `gateway_hook.py` (лог + метрики), `models.py` (evidence
  поля EnforcementOutcome).
- Тесты: 4 новых файла (37 тестов): registry (9), resolver (10), policy
  (15), router/equivalence/perf (13).
- Intent router scope: 343/344 (1 environmental pre-existing —
  test_scheduler_unchanged_after_schedule_probe, /tmp/hgw_reload.* от живого
  gateway; 13/13 после карантина артефактов).
- Offline eval (§36) и canonical + live — в финальном отчёте спринта.

## 12. Дальше

- **Sprint 1.3.1 — Capability Policy Engine hardening** — **DONE**
  (см. `docs/hermes-v2/capability-policy-engine-1.3.1.md`):
  PolicyDecision-модель, канонический ReasonCode, строгая лестница,
  health gate + TTL, fail-closed fallback, policy-метрики; authority
  не расширена, эквивалентность 100%.
- **Sprint 1.3.2 — VERIFIED TOOL EXECUTION CONTRACT** (по брифу; не
  начинать автоматически).
- Фазы B/C (§16) активируются после подтверждённой shadow-эквивалентности:
  Phase B — STATUS_READ enforce, Phase C — SEARCH_READ prod allowlist.
