\# Hermes 2.0 — Sprint 1.5.1 Core Contract Test Harness



\## Role



You are Hermes Core Contract Test Architecture Agent.



\## Mission



Create the executable contract-test foundation for the isolated `hermes\_core` layer.



The purpose is to turn the architectural contracts defined in Sprint 1.4.x into reproducible evidence.



This sprint does NOT connect `hermes\_core` to production runtime.



\---



\## Mode



Implementation of isolated tests + validation.



Tests may be added.



Production runtime must not be changed.



\---



\## Restrictions



DO NOT:



\- modify `gateway/`;

\- modify `agent/`;

\- modify `tools/`;

\- modify `hermes\_state\*`;

\- modify provider adapters;

\- modify delivery ledger;

\- modify TUI;

\- modify cron;

\- modify production runtime ownership;

\- connect `hermes\_core` to production runtime;

\- change database schema;

\- change public runtime APIs;

\- enable migration flags;

\- implement production adapters;

\- change existing production behavior.



Allowed:



\- create isolated tests for `hermes\_core`;

\- create test fixtures;

\- create test-only fake ports;

\- create contract test helpers;

\- create documentation of executed evidence;

\- modify only files required for the isolated contract-test harness.



\---



\# Analyze Existing Infrastructure



Study:



\- `hermes\_core/`

\- `tests/`

\- `scripts/run\_tests.sh`

\- `docs/architecture/application-layer-foundation.md`

\- `docs/architecture/regression-harness-plan.md`

\- `docs/architecture/regression-harness-execution.md`

\- `docs/architecture/migration-readiness-gate.md`

\- `AGENTS.md`

\- `SECURITY.md`



Determine the existing test framework and conventions before creating tests.



Do not introduce another test framework if an existing framework is already authoritative.



\---



\# C1 — Session Contract Tests



Create executable tests for:



\- Session creation;

\- default ACTIVE state;

\- lease acquisition;

\- only one active lease;

\- lease generation increment;

\- session generation increment;

\- release by current owner;

\- release rejection by stale owner;

\- release rejection with stale lease generation;

\- close by current owner;

\- close rejection by stale owner;

\- closed session cannot acquire new lease;

\- lease owner cleared after release;

\- lease owner cleared after close;

\- generation monotonicity;

\- lease\_generation isolation from session generation.



Required stale-owner scenario:



```text

owner A acquires lease N

owner A releases lease

owner B acquires lease N+1

owner A attempts release/close using N

operation MUST fail

session MUST remain owned by B

