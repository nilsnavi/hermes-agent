\# Hermes 2.0 — Sprint 1.4.2 Regression Harness





\## Role



You are Hermes Regression Architecture Agent.





\## Mission



Create a regression safety strategy before runtime refactoring.



This phase defines the minimum validation framework required to safely modify Hermes runtime.





\---



\# Mode



Analysis + test planning.



No implementation.





\---



\# Restrictions



DO NOT:



\- modify production code;

\- modify existing tests;

\- create new tests;

\- refactor modules;

\- change APIs;

\- change database schema.





Only create documentation.





\---



\# Analyze Existing Test Infrastructure





Study:





\- tests/

\- evals/

\- scripts/run\_tests.sh

\- AGENTS.md

\- SECURITY.md

\- docs/architecture/runtime-audit.md

\- docs/architecture/baseline-protection-plan.md





\---



\# Required Analysis Areas





\## 1. Session Regression Coverage





Analyze existing coverage for:





\- session creation

\- resume

\- close

\- expiration

\- concurrent access

\- session rotation

\- compression lineage





Identify:



\- existing tests

\- missing tests

\- critical scenarios





\---



\## 2. Persistence Regression Coverage





Analyze:





\- SQLite

\- WAL

\- migrations

\- registry

\- generation handling

\- recovery





Identify:





\- database invariants

\- required golden tests





\---



\## 3. Runtime Lifecycle Coverage





Analyze:





\- startup

\- shutdown

\- restart

\- workers

\- cron

\- API server

\- deferred execution





Define:



\- lifecycle scenarios

\- failure scenarios





\---



\## 4. Delivery Reliability





Analyze:





\- delivery ledger

\- retry behavior

\- duplicate prevention

\- crash recovery

\- streaming finalization





\---



\## 5. Tool Execution Safety





Analyze:





\- tool registry

\- approval flow

\- capability checks

\- hooks

\- concurrent execution





\---



\## 6. Provider Routing





Analyze:





\- provider resolution

\- fallback chain

\- credentials

\- model routing





\---



\# Create Document





Create:





docs/architecture/regression-harness-plan.md





Document must contain:





\## 1. Current Test Landscape





\## 2. Golden Test Suite Definition





\## 3. Critical Regression Matrix





\## 4. Missing Coverage





\## 5. Test Execution Strategy





\## 6. Migration Gates

Additional section:



\## 7. Hermes Core Contract Validation



Document:



\- domain contract tests

\- application service tests

\- port compatibility checks

\- adapter migration gates



\---



\# Required Output Format





For each critical behavior:





Behavior:



Current protection:



Existing tests:



Missing tests:



Risk:



Priority:





\---

\## 8. Hermes Core Contract Regression



Analyze new isolated architecture layer:



hermes\_core/





Validate:





\### Session Contract





Required scenarios:



\- session creation

\- lease acquisition

\- lease release by owner

\- stale lease rejection

\- close by current lease owner

\- close rejection by stale owner

\- generation increment rules

\- lease\_generation isolation





\### Delivery Contract





Validate:



\- DeliveryResult semantics

\- success handling

\- failed delivery handling

\- retryable failures

\- delivery state transitions





\### Tool Execution Contract





Validate:



\- ToolExecutionContext creation

\- immutable context behavior

\- capability grant propagation

\- approval boundary





\### Routing Contract





Validate:



\- immutable RouteDecision

\- provider precedence

\- credential reference isolation



\# Acceptance Criteria





✓ No code changes



✓ No tests changed



✓ Regression strategy documented



✓ Golden test suite identified



✓ Migration safety criteria defined
✓ Existing runtime remains authoritative



✓ hermes\_core remains isolated



✓ Migration can be validated without runtime replacement

