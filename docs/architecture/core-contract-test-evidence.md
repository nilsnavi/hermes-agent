# Core Contract Test Evidence

Дата: 2026-09-21. Sprint: 1.5.1. Проверенная ревизия: `0d339867edd8425acd6dbced7e24037695c0dff7`.

## 1. Test Scope

Prompt `.ai/prompts/sprint-1.5.1-core-contract-tests.md` был усечён после C1. Продолжение задания из пользовательского вложения требует завершить C2, C3 и C4. Поэтому этот harness содержит только изолированные C1–C4 tests; production adapters и runtime integration не добавлялись.

Созданы только test files под `tests/hermes_core/`. Они используют pytest, текущий авторитетный test framework, и test-only recording/fake ports. Production runtime и production implementation `hermes_core` не изменялись.

## 2. C1 Session Evidence

- создание `Session` и состояние ACTIVE по умолчанию;
- первый lease и запрет второго одновременного lease;
- отдельные изменения `generation` и `lease_generation`;
- release только текущим owner с актуальным lease generation;
- отказ для другого owner и stale generation без мутации state;
- обязательный сценарий A/N → release → B/N+1 → stale release/close A/N;
- close только текущим owner, очистка owner и запрет нового lease после close;
- монотонность session generation и изменение lease generation только при acquire;
- `SessionService` create/resume/resume_by_key, persistence только успешных transitions, отказ второго acquire и missing-session errors.

**Contract:** lifecycle defaults, single lease, generation fencing, current/stale release and close, closed-session rejection, service persistence behavior.

**Test:** `tests/hermes_core/test_session_contract.py` (11 cases, включая две параметризованные stale-owner ветви).

**Expected:** stale owner A cannot release or close newer owner B's lease; rejected operations do not mutate state; generation counters follow the current domain implementation.

**Actual:** 11 passed. C1 stale-owner, close/reacquire and SessionService recording-port scenarios passed.

**Result:** PASS for isolated C1 in-memory/application contract.

**Evidence:** final combined canonical runner receipt below; Python 3.13.7, Windows, pytest 9.1.1.

**Known limitation:** no atomic SessionDB/CAS, WAL, multi-process fencing, routing-index or compression-lineage proof. B1/B2/B7 remain open.

## 3. C2 Delivery Evidence

**Contract:** initial `PENDING`, `begin_attempt()` to `ATTEMPTING`, successful transport to `DELIVERED`, unsuccessful transport to `FAILED`, immutable `DeliveryResult` fields, no automatic retry, and exception classification as currently implemented.

**Test:** `tests/hermes_core/test_delivery_contract.py` (7 cases).

**Expected:** transport success → `DELIVERED`; transport failure → `FAILED`; retryable is transport metadata and does not invoke a second send; delivery cannot be marked delivered before a successful attempting state; transport exception is re-raised after state becomes FAILED.

**Actual:** 7 passed. Recording transport observed `ATTEMPTING`; calls remained exactly one for retryable and non-retryable results; exception was re-raised and delivery became FAILED.

**Result:** PASS for the current isolated state-machine behavior.

**Evidence:** final combined runner receipt; no network or ledger access.

**Known limitation:** `DeliveryService` returns only `DeliveryState` and drops `external_id`, `retryable` and `error` for its caller; unknown ACK/abandoned states are absent. B3 is explicitly **not resolved**.

## 4. C3 Tool Execution Evidence

**Contract:** exact caller context (`session_id`, `turn_id`, `tool_call_id`, `capability_grant`, `approved`) and argument mapping reach `ToolExecutorPort`; context is frozen; empty tool name is rejected by the current service contract.

**Test:** `tests/hermes_core/test_tool_execution_contract.py` (4 cases) with a deterministic recording executor.

**Expected:** `caller context → ExecutionService → ToolExecutorPort` without reconstruction, replacement or mutation; `approved=False` remains a propagated value and does not become an invented enforcement rule.

**Actual:** 4 passed. The exact arguments object and logical context were recorded; frozen field mutation raised `FrozenInstanceError`; empty name raised `ValueError` before executor call.

**Result:** PASS for propagation only.

**Evidence:** final combined runner receipt; fake executor performs no subprocess, network or registry call.

**Known limitation:** no capability validation, principal/profile binding, expiry/revocation, approval receipt or final post-middleware enforcement exists in this contract. B4 is explicitly **not resolved**.

## 5. C4 Routing Evidence

**Contract:** `RoutePurpose`, frozen `RouteDecision`, route metadata propagation and `ProviderRouter` delegation through `ProviderPort`.

**Test:** `tests/hermes_core/test_routing_contract.py` (4 cases) with a deterministic recording provider.

**Expected:** provider, model, endpoint, api mode, opaque credential reference and route purpose are preserved; router forwards requested provider/model/purpose/options exactly and returns provider result; route decision fields are immutable.

**Actual:** 4 passed. Current field name `route_purpose` was tested as implemented; no alias to `purpose` was introduced. Credential reference is a non-secret sentinel only.

**Result:** PASS for current forwarding/value-object contract.

**Evidence:** final combined runner receipt; endpoint uses `example.invalid`; no credentials or provider SDK were accessed.

**Known limitation:** provider precedence, fallback, credential-pool recovery, profile scope and prompt-cache behavior are not implemented in core tests. The `purpose`/`route_purpose` naming discrepancy remains. B5 is explicitly **not resolved**.

## 6. Negative Tests

- stale owner and stale lease generation release/close are rejected without state mutation (C1);
- second active lease and acquire on CLOSED session are rejected (C1);
- delivery failure and transport exception produce FAILED; no automatic retry is triggered (C2);
- `mark_delivered()` before ATTEMPTING and after FAILED raises `ValueError` (C2);
- immutable `ToolExecutionContext` and `RouteDecision` mutations raise `FrozenInstanceError` (C3/C4);
- empty tool name is rejected before the executor is called (C3).

The tests do not invent unknown-ACK, capability-enforcement or provider-precedence invariants; those absent contracts are recorded as gaps.

## 7. Isolation Checks

- All four files live under `tests/hermes_core/`.
- Fakes are deterministic recording objects and perform no subprocess, network, credential, registry, gateway or production database access.
- The final run used `--confcutdir=tests/hermes_core`, avoiding unrelated global production fixtures while retaining the repository runner's clean environment and per-file subprocess isolation.
- No source-text grep is used as behavioral proof.
- No files under `gateway/`, `agent/`, `tools/`, `hermes_state*`, provider adapters, delivery ledger, TUI or cron were modified.

## 8. Test Execution

## Environment

| Параметр | Значение |
|---|---|
| OS | Windows (`win32`) |
| Python | 3.13.7 |
| pytest | 9.1.1 |
| pluggy | 1.6.0 |
| Canonical runner | `scripts/run_tests.sh` → `scripts/run_tests_parallel.py` |
| Runner isolation | `TZ=UTC`, `LANG=C.UTF-8`, `PYTHONHASHSEED=0`, clean environment, per-file subprocess |
| Python environment | Временный `%TEMP%\hermes-core-contract-151`; репозиторий и dependency manifests не изменены |

В проекте не было `.venv`/`venv` с pytest. Для запуска во временное окружение установлен pytest 9.1.1. Полный production dependency graph не устанавливался.

## Exact commands and results

### Attempt 1 — system bash

```powershell
bash scripts/run_tests.sh tests/hermes_core/test_session_contract.py
```

Result: `INFRA_ERROR`, exit code 1. Системный `bash` попытался создать WSL instance и завершился `Bash/Service/CreateInstance/E_ACCESSDENIED`. Tests не собирались и не выполнялись.

### Attempt 2 — Git Bash bin entry

```powershell
& 'C:\Program Files\Git\bin\bash.exe' scripts/run_tests.sh tests/hermes_core/test_session_contract.py
```

Result: `INFRA_ERROR`, exit code 1. В унаследованном PATH отсутствовал `dirname`; runner остановился до выбора Python.

### Attempt 3 — Git Bash usr entry

```powershell
& 'C:\Program Files\Git\usr\bin\bash.exe' scripts/run_tests.sh tests/hermes_core/test_session_contract.py
```

Result: `INFRA_ERROR`, exit code 1. Та же ошибка `dirname: command not found`; tests не выполнялись.

### Attempt 4 — corrected Git Bash PATH

```powershell
& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; scripts/run_tests.sh tests/hermes_core/test_session_contract.py'
```

Result: `INFRA_ERROR`, exit code 1. Runner запустился, но корректно отказал: local venv с pytest и подходящий `HERMES_PYTHON` отсутствовали.

### Environment preparation

```powershell
$testEnv = Join-Path $env:TEMP 'hermes-core-contract-151'; py -3.13 -m venv $testEnv
& "$env:TEMP\hermes-core-contract-151\Scripts\python.exe" -m pip install pytest
```

Result: временное окружение создано; установлен pytest 9.1.1 и его зависимости. Файлы зависимостей репозитория не менялись.

### Attempt 5 — canonical runner with pytest-only environment

```powershell
& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Users/Navitech-home/AppData/Local/Temp/hermes-core-contract-151/Scripts/python.exe; scripts/run_tests.sh tests/hermes_core/test_session_contract.py'
```

Result: `INFRA_ERROR`, exit code 1. Pytest собрал 11 cases, но global `tests/conftest.py` autouse fixture импортировал production dependency chain и остановил setup на `ModuleNotFoundError: No module named 'yaml'`. Итог runner: 0 tests passed, 0 failed, 11 setup errors. Это не contract failure.

### Final C1-C4 required test run

```powershell
& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Users/Navitech-home/AppData/Local/Temp/hermes-core-contract-151/Scripts/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'
```

Result: `PASS`, exit code 0.

```text
Discovered 4 test files (~24 tests) under ['tests\\hermes_core']; running with -j 24
test_session_contract.py: 11 passed; test_delivery_contract.py: 7 passed;
test_tool_execution_contract.py: 4 passed; test_routing_contract.py: 4 passed
Runner summary: 4 files, 26 tests passed, 0 failed, 1.3s
```

`--confcutdir=tests/hermes_core` ограничивает pytest discovery изолированным core-contract каталогом и не загружает global production fixtures. Канонический runner продолжает обеспечивать clean environment и per-file subprocess isolation. Это соответствует scope: тесты не импортируют gateway, agent, tools, provider adapters или SessionDB.

### Required compile/import checks

```powershell
python -m compileall hermes_core
```

Result: exit code 0; `hermes_core`, `application`, `domain` и `ports` compiled successfully.

```powershell
python -c "import hermes_core; print('hermes_core OK')"
```

Result: exit code 0; output `hermes_core OK`.

Environment: Windows `win32`, Python 3.13.7 for test runner; compile/import used the repository `python` command and completed with exit code 0. Commit SHA: `0d339867edd8425acd6dbced7e24037695c0dff7`.

## 9. Known Gaps

Статусы C1–C4 для перечисленных isolated contracts: **PASS** на указанной ревизии и среде.

Доказательство ограничено изолированным слоем:

- оно не подтверждает atomic persistence/CAS между процессами;
- recording port не подтверждает совместимость с SessionDB, WAL, routing index или compression lineage;
- оно не закрывает route-exception lease cleanup в `RuntimeApplication`;
- оно не подтверждает C2 unknown-ACK/crash recovery parity;
- оно не подтверждает C3 capability enforcement или production tool pipeline parity;
- оно не подтверждает C4 resolver precedence/fallback/credential isolation parity;
- оно не меняет итоговый `NO-GO` для production runtime migration из `migration-readiness-gate.md`.

B1–B7 из readiness gate остаются открытыми, если их требуемые evidence не получены независимо. В частности, этот test run не доказал adapter parity, atomic persistence/CAS, SessionDB/WAL safety, delivery ACK recovery, capability enforcement, provider precedence/fallback, migration-controller readiness или rollback readiness.

## 10. Readiness Impact

C1–C4 дают воспроизводимое evidence для текущих in-memory/domain/application contracts и снижают прежний пробел «нет прямых core tests». Они не являются разрешением на migration phase 1/2 и не закрывают readiness blockers B1–B7. Current runtime остаётся authoritative; production adapters, migration flags, schema/API changes, ownership transfer, commit и push не выполнялись.

Production runtime, ownership, database schema, public runtime APIs, migration flags и adapters не изменены. Commit и push не выполнялись.
