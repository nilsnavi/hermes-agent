# Hermes 2.0 — Sprint 1.5.1 Core Contract Test Harness

## Role

You are the Hermes Core Contract Test Architecture Agent.

## Mission

Create the executable contract-test foundation for the isolated `hermes_core` layer. Turn the architectural contracts from Sprint 1.4.x into reproducible evidence for the current domain and application contracts.

This sprint validates the isolated core contract only. It does not migrate runtime ownership, connect `hermes_core` to production, create adapters, or authorize migration. The current runtime remains authoritative throughout the sprint.

## Mode

Implementation of isolated tests plus validation and evidence documentation.

## Restrictions

Do not:

- modify production runtime code or existing runtime ownership;
- modify `gateway/`, `agent/`, `tools/`, `hermes_state*`, provider adapters, delivery ledger, TUI or cron;
- connect `hermes_core` to production runtime;
- implement production adapters or capability enforcement;
- replace `SessionState`, the delivery ledger, provider resolver or tool registry;
- change the database schema or public runtime APIs;
- enable migration flags or remove legacy owners;
- change existing production behavior;
- use real credentials, production databases, network calls or subprocesses in the isolated fakes;
- modify existing contract tests or weaken their assertions;
- claim B1–B7 are resolved or issue migration authorization.

Allowed changes are limited to new or required isolated tests under `tests/hermes_core/`, test-only fake/recording ports and the existing evidence document `docs/architecture/core-contract-test-evidence.md`.

## Analyze Existing Infrastructure

Before adding tests, study:

- `hermes_core/` domain, application and ports;
- `tests/` conventions and existing runtime behavior tests;
- `scripts/run_tests.sh` and `scripts/run_tests_parallel.py`;
- `docs/architecture/application-layer-foundation.md`;
- `docs/architecture/regression-harness-plan.md`;
- `docs/architecture/regression-harness-execution.md`;
- `docs/architecture/migration-readiness-gate.md`;
- `docs/architecture/adapter-boundary-design.md`;
- `docs/architecture/capability-policy-engine.md`;
- `docs/architecture/runtime-migration-controller.md`;
- `AGENTS.md` and `SECURITY.md`.

Use the repository's existing pytest framework. Do not introduce another test framework. Treat the current `hermes_core` implementation as the contract under test: when an expected production guarantee is absent, record the gap instead of modifying production code to make the test pass.

## C1 — Session Contract Tests

Create executable tests in `tests/hermes_core/test_session_contract.py` for:

- `Session` creation and default `ACTIVE` state;
- lease acquisition and only one active lease;
- lease-generation and session-generation increments;
- release by the current owner;
- rejection of stale owner and stale lease generation on release;
- close by the current owner and rejection of stale close;
- closed session cannot acquire a new lease;
- lease owner is cleared after release and after close;
- session generation is monotonic;
- `lease_generation` is isolated from session `generation`;
- `SessionService` create/resume/resume-by-key, successful persistence and rejected transitions through a test-only recording repository.

Required stale-owner scenario:

```text
owner A acquires lease N
owner A releases lease
owner B acquires lease N+1
owner A attempts release/close using N
operation MUST fail
session MUST remain owned by B
```

Do not claim atomic SessionDB/CAS, WAL, multi-process fencing, routing-index or compression-lineage safety from these in-memory/application tests.

## C2 — Delivery Contract Tests

Create `tests/hermes_core/test_delivery_contract.py` with a deterministic recording transport. Cover:

- initial `PENDING` state;
- `begin_attempt()` and `ATTEMPTING` state;
- successful transport → `DELIVERED`;
- unsuccessful transport → `FAILED`;
- retryable and non-retryable `DeliveryResult` values;
- `external_id` and `error` fields as transport result data;
- success is required before `DELIVERED`;
- transport exception behavior.

Verify explicitly:

```text
transport success   -> DELIVERED
transport failure   -> FAILED
retryable result    -> no automatic second send
transport exception -> FAILED and exception is re-raised
```

The core application layer must not silently perform retry orchestration. If `DeliveryService` loses `external_id`, `retryable` or error classification for its caller, test the contract that actually exists and record that limitation. Do not add unknown-ACK or abandoned states in this sprint and do not claim B3 is resolved.

## C3 — Tool Execution Contract Tests

Create `tests/hermes_core/test_tool_execution_contract.py` with a test-only recording `ToolExecutorPort`. Cover:

- `ToolExecutionContext` construction;
- preservation of `session_id`, `turn_id`, `tool_call_id`;
- propagation of `capability_grant` and `approved`;
- immutable context fields;
- empty tool name rejection where defined by the current service;
- exact argument propagation;
- exact logical context forwarding through:

```text
caller context -> ExecutionService -> ToolExecutorPort
```

The service must not reconstruct, replace or mutate execution identity or arguments. Do not implement capability enforcement and do not make `approved=False` block execution when the current production contract only propagates that value. Do not claim B4 is resolved.

## C4 — Routing Contract Tests

Create `tests/hermes_core/test_routing_contract.py` with a deterministic recording `ProviderPort`. Cover:

- all current `RoutePurpose` values;
- `RouteDecision` construction;
- immutability of `RouteDecision`;
- provider, model, endpoint and `api_mode` propagation;
- opaque `credential_reference` propagation without real secrets;
- current route-purpose propagation;
- `ProviderRouter` delegation through `ProviderPort`, including requested provider/model/purpose/options and returned decision identity.

If the implementation uses `route_purpose` rather than `purpose`, test the current field and record the naming discrepancy. Do not add a test-only alias. Do not implement provider precedence, fallback, credential-pool recovery, prompt-cache behavior or production provider adapters. Do not claim B5 is resolved.

## Test Isolation Requirements

All C1–C4 tests remain under `tests/hermes_core/`. Test-only fakes must be deterministic, record calls and arguments, and have no subprocess, network, credential, gateway, tool-registry, provider-SDK, SessionDB or production-database access. Use safe sentinel values such as `example.invalid` and opaque reference strings.

Use `--confcutdir=tests/hermes_core` when the repository-wide conftest would load unrelated production dependencies. This is an isolation boundary for these tests, not a production behavior change. Do not use source-text grep as the sole behavioral proof.

## Concurrency Boundary

These tests validate the current in-memory/domain/application contracts sequentially and through deterministic recording fakes. They do not prove cross-thread or cross-process atomicity, distributed leases, SQLite/WAL behavior, or worker lifecycle. Do not add sleeps, timing races or fake operating systems. Any concurrency claim beyond the tested single-object transitions is a known limitation and remains covered by B1/B2/B7 readiness gates.

## Negative Tests

Include meaningful negative cases supported by the current implementation:

- stale owner and stale lease generation release/close;
- second active lease and acquire after close;
- failed delivery, retryable/non-retryable no-retry behavior and transport exception;
- premature delivery acknowledgement;
- immutable `ToolExecutionContext` mutation;
- empty tool name;
- immutable `RouteDecision` mutation.

Do not invent invariants that `hermes_core` does not currently define. Record missing enforcement or outcome semantics as a gap.

## Canonical Test Execution

Run all C1–C4 together through the repository runner:

```powershell
'&C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Users/Navitech-home/AppData/Local/Temp/hermes-core-contract-151/Scripts/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'
```

Adapt PowerShell quoting only as needed. The canonical runner must retain clean-environment setup, UTC/C.UTF-8, deterministic hash seed and per-file subprocess isolation. Record collected, passed, failed, skipped, retried and infrastructure-error counts. Do not claim full repository regression PASS unless the full suite was actually run.

Also run:

```powershell
python -m compileall hermes_core
python -c "import hermes_core; print('hermes_core OK')"
```

The source-of-truth completed run is four files and 26 passing tests: C1 11, C2 7, C3 4 and C4 4. The completion evidence records the exact environment, command, exit code and commit SHA.

## Evidence Document Requirements

Update only `docs/architecture/core-contract-test-evidence.md`. It must contain these sections:

1. Test Scope
2. C1 Session Evidence
3. C2 Delivery Evidence
4. C3 Tool Execution Evidence
5. C4 Routing Evidence
6. Negative Tests
7. Isolation Checks
8. Test Execution
9. Known Gaps
10. Readiness Impact

For every C1–C4 contract record:

```text
Contract:
Test:
Expected:
Actual:
Result:
Evidence:
Known limitation:
```

Record exact commands, exit codes, collected/passed/failed/skipped counts, environment and commit SHA. Report infrastructure failures separately from test failures. Do not modify the evidence document when repairing this prompt unless the sprint itself is being executed.

## Readiness Boundary

Even when C1–C4 pass, this sprint does not prove:

- production migration readiness;
- adapter parity;
- atomic persistence/CAS;
- SessionDB/WAL safety;
- delivery crash/ACK recovery parity;
- capability enforcement;
- provider precedence/fallback parity;
- migration-controller readiness;
- rollback readiness.

B1–B7 remain open unless independently proven by their required evidence. The current runtime remains authoritative. Contract-test PASS is evidence for isolated contracts only, not migration authorization or a production rollout decision.

## Acceptance Criteria

Sprint 1.5.1 is complete only when:

- C1 remains passing and the stale-owner invariant is present;
- C2, C3 and C4 are implemented and executed;
- negative cases exist;
- tests remain isolated under `tests/hermes_core/`;
- fakes are test-only and do not access production systems or credentials;
- production runtime and production `hermes_core` implementation are unchanged;
- no production adapters, migration flags, schema/API changes or ownership transfer are introduced;
- evidence document contains actual results and known limitations;
- B1–B7 are not claimed resolved;
- no migration authorization is produced;
- no commit or push is performed.

Stop after Sprint 1.5.1 completion.

