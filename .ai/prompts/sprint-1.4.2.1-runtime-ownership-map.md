\# Hermes 2.0 — Sprint 1.4.2.1 Runtime Ownership Map





\## Role



You are Hermes Architecture Ownership Mapping Agent.





\## Mission



Create a responsibility ownership map before runtime refactoring.



The goal is to identify:



\- who owns each responsibility today;

\- where responsibilities are duplicated;

\- what future application-layer ownership should be.





\---



\# Mode



Architecture analysis only.





\---



\# Restrictions



DO NOT:



\- modify production code;

\- move files;

\- rename classes;

\- refactor modules;

\- change APIs;

\- create implementation code.





Only documentation.





\---



\# Read First





Analyze:





\- docs/architecture/runtime-audit.md

\- docs/architecture/baseline-protection-plan.md

\- docs/architecture/regression-harness-plan.md



Read:



\- AGENTS.md

\- SECURITY.md





\---



\# Analyze Ownership Areas





\## 1. Runtime Lifecycle





Map:





Current owner:



\- startup

\- shutdown

\- restart

\- recovery

\- workers





Future owner:





Define recommended Application Layer boundary.





\---



\## 2. Session Management





Map:





Current owner:



\- session creation

\- resume

\- close

\- lease

\- generation

\- compression





Future owner:





SessionService responsibilities.





\---



\## 3. State Persistence





Map:





Current owner:



\- SQLite

\- WAL

\- migrations

\- registry

\- recovery





Future owner:





Persistence abstraction boundary.





\---



\## 4. Tool Execution





Map:





Current owner:



\- registry

\- discovery

\- approval

\- execution

\- hooks

\- result storage





Future owner:





ExecutionService boundary.





\---



\## 5. Provider Routing





Map:





Current owner:



\- resolver

\- fallback

\- credentials

\- model selection





Future owner:





ProviderRouter boundary.





\---



\## 6. Delivery System





Map:





Current owner:



\- ledger

\- retries

\- acknowledgement

\- recovery





Future owner:





DeliveryService boundary.





\---



\# Required Output





Create:





docs/architecture/runtime-ownership-map.md





Document structure:





\# Current Ownership Map





Table:





| Responsibility | Current Module | Current Owner | Risk |





\---





\# Proposed Ownership Model





Table:





| Responsibility | Future Component | Migration Priority |





\---





\# Dependency Boundaries





Describe:





Allowed dependencies:



interfaces



↓



application



↓



domain



↓



infrastructure





Forbidden dependencies.





\---





\# Migration Order





Recommend:





1\.

2\.

3\.





with risk explanation.





\---



\# Acceptance Criteria





✓ Documentation only



✓ No source code changes



✓ Ownership conflicts identified



✓ Future boundaries proposed



✓ Migration order defined

