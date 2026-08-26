# Phase 5 — Execution Boundary & Coding Agent Security Hardening

**Статус:** PASS (после полного canonical + security review — см. разделы 10–11)
**Ветка:** `sprint/1.3.7-narrow-production-canary`
**HEAD:** `9389dea5aafd6ef9f1d8978f6db61400b1b38bcd` (неизменён — production не тронут)
**Backup:** `~/hermes-backup-sprint-1.4-phase5-security-boundary-20260826-100151` (SHA256SUMS 960/960 OK)

---

## 1. Цель

Закрыть security-блокер между Agent Platform Control Plane и существующим
Hermes Execution Kernel: сертифицировать **единственный допустимый execution path**:

```
AgentCapabilityIntent -> PlatformPolicy -> CapabilityRouter
      -> SystemBoundary -> VerifiedToolExecutor -> SealedSandbox
```

Никакого альтернативного пути быть не должно. CodingAgent остаётся
`READ_ONLY_OR_SHADOW` (write_files=DENIED, execute_code=DENIED) — Phase 5 НЕ
включает production mutation-capable Coding Agent.

## 2. Scope (12 пунктов)

| # | Scope item | Реализация | Файл |
|---|---|---|---|
| 1.1 | Agent capability request contract | `AgentCapabilityIntent` (bounded, вердикт не несёт) | `intent.py` |
| 1.2 | Platform Policy → kernel admission bridge | `SecurityBoundaryGate` композирует `PolicyEvaluator` → `CapabilityRouterSeam` → `SystemBoundarySeam` → `ToolExecutorSeam` → `SealedSandbox` | `admission.py` |
| 1.3 | Mandatory SystemBoundary composition | отсутствующий/ошибочный порт ⇒ DENY (`COMPONENT_MISSING`/`UNKNOWN`) | `admission.py` |
| 1.4 | Mandatory VerifiedToolExecutor composition | `is_ready()` обязателен; not-ready ⇒ DENY | `admission.py` |
| 1.5 | Sandbox adapter sealing | `SealedSandbox`, приватный gate-token; вне прямого вызова — `SealViolation` | `seal.py` |
| 1.6 | Caller verdict rejection | `CallerClaim` = данные (аудит), никогда не authority; `_allowed()` отклоняет строки `APPROVED/ALLOW/PASS` | `intent.py`, `admission.py` |
| 1.7 | REVALIDATE_REQUIRED fail-closed | disposition `REVALIDATE_REQUIRED` ⇒ DENY; `NON_EXECUTABLE_DISPOSITIONS` расширен `SIDE_EFFECT_UNKNOWN` | `admission.py`, `status.py` |
| 1.8 | Direct adapter bypass prevention | `SealedSandbox.run` только с приватным токеном; использование bolt | tests seal/adversarial |
| 1.9 | CodingAgent read-only enforcement | `CODING_READ_ONLY_CAPABILITIES`(4) / `CODING_FORBIDDEN_CAPABILITIES`(7); классификатор | `coding.py` |
| 1.10 | AgentRegistry runtime-owned allowlist | `SystemAgentRuntime` reject non-canonical impl, seal-дайджест, `assert_registry_sealed()`, `AgentRegistryDrift` | `agent_system/runtime.py`, `exceptions.py` |
| 1.11 | Execution audit linkage | `AuditTrail` append-only, immutable records | `audit.py` |
| 1.12 | Security / adversarial certification | 10-вопросный adversarial-риевью → см. §11 | `tests/agent_security_boundary/test_adversarial.py` |

## 3. NON-GOALS (подтверждено, не включено)

- CodingAgent: write_files, execute_code, shell, subprocess, git-mutation,
  install, service-mutation, production-file-mutation, SYSTEM_CONTROL,
  generic SERVICE_CONTROL, direct adapter access — **все запрещены**.
- Никакого изменения production-полномочий.
- Никакого commit/tag/push, никакой production-активации.

## 4. Единственный execution path

`AgentCapabilityIntent → PlatformPolicy → CapabilityRouter → SystemBoundary
→ VerifiedToolExecutor → SealedSandbox`.

Запрещено (отсутствует в коде и покрыто adversarial-тестами): Agent→Adapter,
Agent→Executor-direct, Agent→subprocess/filesystem, Agent→systemctl/shell,
Planner→tool, Supervisor→tool, MessageBus→tool, Memory→tool.

## 5. Mandatory boundary / fail-closed

В `SecurityBoundaryGate.__init__` пять обязательных портов:
`policy, capability_router, system_boundary, executor, sandbox`. `missing_components()`
перечисляет отсутствующие; `admit()` возвращает `DENY/COMPONENT_MISSING` без
allow-fallback для любого отсутствующего/несконфигурированного/ошибшегося порта.
Проверено тестами `test_missing_mandatory_component_is_deny` (по каждому порту),
`test_component_that_errors_is_deny`, `test_not_ready_executor_is_deny`.

## 6. Caller verdict = DATA (не authority)

- `CallerClaim` (approval/verdict/allow/risk_score/policy_result/boundary_result)
  сериализуется в аудит через `as_audit_data()` с флагом `is_authority=False`.
- `_allowed()` допускает allow только для явного `bool True` (или атрибута
  `.allowed is True`). Строки `"APPROVED"/"ALLOW"/"PASS"` → `False`.
- Подделанные claims не меняют решение и не «спасают» DENY.

## 7. Sandbox sealing / direct bypass

`SealedSandbox.run(payload, *, gate_token=None)` требует приватный модульный
токен `_GATE_TOKEN`; без него — `SealViolation`. Адаптер не экспортируется в
публичный API (`seal.py` НЕ в `__all__` пакета как callable; публичен только
`SealedSandbox` с sealed-методом). `admission_status` этой фазы sandbox НЕ
вызывает (`call_count==0` после allow, проверено тестами).

## 8. CodingAgent read-only

`CODING_READ_ONLY_CAPABILITIES = {read_repository, inspect_files, analyze_code, produce_patch_proposal}`.
`CODING_FORBIDDEN_CAPABILITIES = {write_files, execute_code, install_dependency, git_commit, git_push, run_shell, service_control}` (зафиксировано, не расширяемо).
Мутация, даже объявленная в AgentDefinition, ⇒ hard-DENY. `classify_side_effect`
мапит мутационные токены в WRITE/EXECUTE/SERVICE_MUTATION (не UNKNOWN).

## 9. Registry runtime-owned / non-expanding / version-sync

- `SystemAgentRuntime.__init__`: только `SYSTEM_IMPLEMENTATION_IDS`; caller-
  supplied registry с неканоническим impl ⇒ `UnknownImplementation`.
- `_seal_snapshot()`: SHA-256 канонического снапшота; `assert_registry_sealed()`
  ⇒ `AgentRegistryDrift` при внешнем дрейфе (прямая мутация реестра).
- Легитимная re-registration переуплотняет снапшот (без ложного дрейфа).
- `_require_canonical_definition`: запрет capability-smuggling, запрет
  write_files/execute_code, запрет permissions-beyond-canonical.
- Lifecycle version синкронизирован с version определения (definitions v1 → lifecycle v1).

## 10. Полный canonical

Phase 5 scoped canonical (Phases 1–5, зелёные control-plane пакеты):
**459 passed / 0 failed** (`agent_runtime` 109, `agent_orchestration` 106,
`agent_system` 102, `agent_security_boundary` 114, `platform_policy` 28).

Новые тесты Phase 5: **151** (после закрытия B1/B2; 114 в
`tests/agent_security_boundary/` + 26+11 hardening `tests/agent_system`).

Полный canonical: **3160 files, 33475 passed, 101 failed, 285 skipped**
(100% за 1030.4s, 16 workers). По сравнению с Phase 4 (3151 files / 33324 passed
/ 101 failed / 285 skipped): +9 test-файлов и **+151 passed**, а число failed
(101) и skipped (285) не изменилось ⇒ фаза НЕ вносит новых падений.

**NEW_REGRESSIONS=0** (классификатор `scripts/classify_phase5.py`): 75 упавших
файлов — все `PROVEN_PRE_EXISTING` (пустой `git diff` vs HEAD, 0 coupling с
`agent_security_boundary`/`agent_system`, 0 файлов фазы среди упавших).

## 11. AST-механический гейт

`scripts/scan_security_boundary.py`:
`SCANNED_FILES=17`, `F1/F2/F3_HITS=0`, **`UNAUTHORIZED_EXECUTION_PATHS=0`**.
Классифицированы: C1 — `ports.py:59 def execute` (Protocol-декларация, не вызов);
C3 — `ports.py` строки классификатора operation-name (данные, не исполнение).

## 12. Независимый adversarial-риевью (10 вопросов)

Первичный риевью (deleg): **VERDICT=FAIL, BLOCKING_FINDINGS=2**. Обе находки были
реальными и закрыты:

- **B1 (Q2 — байпас печати):** `SealedSandbox._gate_token()` — публичный
  classmethod, возвращавший приватный seal-токен; через `gate.sealed_sandbox()`
  любой caller мог выполнить `run(payload, gate_token=..._gate_token())` ⇒ прямой
  `adapter.run()` без единой стадии пути. **Закрытие:** метод убран (теперь
  `AttributeError`); токен `_GATE_TOKEN` не имеет никакого публичного доступа
  (нет classmethod/атрибута/в `__all__`); `run` невызовем извне; `call_count`
  гарантированно 0. Тесты: `test_no_public_accessor_returning_the_seal_token`,
  `test_run_is_uncallable_without_an_obtainable_token`.
- **B2 (Q5 — доверие caller-классификации):** гейт доверял заявленному
  `intent.side_effect_class`; объявив `READ_ONLY` на не-запрещённом мутационном
  токене, проходили `MUTATION_CLASSES` и `UNKNOWN`-ветку ⇒ `ALLOW_READ_ONLY`.
  Классификаторы были dead code. **Закрытие:** `admit` теперь сам детерминированно
  классифицирует capability через `classify_side_effect` (+ fallback
  `side_effect_of_operation`); мутация, если ЕЁ класс (заявленный ЛИБО выведенный)
  в `MUTATION_CLASSES` ⇒ DENY; если ЛИБО класс `UNKNOWN` ⇒ HUMAN_REVIEW (никогда
  auto-allow). Обнаружено adversarial-тестами. Тесты: `test_b2_under_declared_read_only_cannot_bypass`, `test_b2_legit_unclassified_capability_is_human_review_not_allow`.

Повторный независимый риевью (подтверждение закрытия B1/B2): **BLOCKING_FINDINGS=0, VERDICT=PASS**.
Итог по всем 10 вопросам после фиксов: 10/10 PASS. Три non-blocking-заметки
(переносится): (i) `_GATE_TOKEN` — module-global, доступен импортом из
`agent.agent_security_boundary.seal` для произвольного in-process кода;
private-by-convention, бинд-слой при желании закроет через closure/default-arg;
(ii) capabilities, классифицируемые как NETWORK, проходят admission как read-only
(не исполнение, безвредно для фазы); (iii) две карты классификаторов
(`coding.classify_side_effect` и `ports.side_effect_of_operation`) независимы —
безопасно, т.к. гейт OR-ит обе в сторону DENY/HUMAN_REVIEW; единый источник — будущий рефакторинг.

## 14. Риски / нереализованное (переносится)

1. **Registry guard opt-in:** `SecurityBoundaryGate(registry=None)` пропускает
   drift + membership-проверки. В production композиция ОБЯЗАНА всегда инжектить
   runtime-owned registry. Не-блокер, но критичный для бинд-слоя.
2. **Audit in-memory:** `AuditTrail` — `list`; записи frozen, но контейнер не
   tamper-evident/персистентен. Корректно относительно authority; персистентность —
   будущая работа.
3. **`SideEffectClass.NETWORK` не в `MUTATION_CLASSES`:** сетевые capabilities,
   не входящие в запрещённый set, проходят read-only admission без отдельного
   scrutiny. Не-блокер (не исполнение); будущее hardening — добавить NETWORK к
   scrutiny или расширить мутационную политику.

## 13. Production-untouched

- HEAD неизменён: `9389dea5aafd6ef9f1d8978f6db61400b1b38bcd`.
- staged=0; Phase 5 изменил **0 tracked-файлов** (все изменения — новые
  untracked файлы control plane).
- Показанные в `git status` tracked-правки `agent/multi_service_execution/*`,
  `docs/codemap/*`, `tests/multi_service_execution/*` — пре-существующие из
  более раннего спринта multi-service (1.3.19), не относятся к этой фазе и не
  изменялись мной.
- Локальный sprint-хост не содержит unit `hermes-gateway.service` (активны
  `hermes-dashboard`, `omniroute`); сервисы мной не останавливались/не менялись.