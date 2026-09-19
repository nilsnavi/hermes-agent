\# Hermes 2.0 — Sprint 1.4.3 Adapter Boundary Design





\## Role



You are Hermes Adapter Architecture Agent.





\## Mission



Design adapter boundaries required for future Hermes runtime migration.



The goal is to define how existing runtime components can implement hermes\_core ports without breaking current ownership.





\## Mode



Architecture analysis only.



No implementation.





\## Restrictions



DO NOT:



\- modify production code;

\- modify existing tests;

\- create adapters;

\- change runtime wiring;

\- replace existing owners;

\- modify database schema.





Only create documentation.





\## Analyze



Study:



\- hermes\_core/

\- docs/architecture/application-layer-foundation.md

\- docs/architecture/regression-harness-plan.md

\- docs/architecture/regression-harness-execution.md

\- docs/architecture/runtime-ownership-map.md

\- existing runtime owners:

&#x20; - hermes\_state

&#x20; - gateway

&#x20; - tools

&#x20; - provider adapters

&#x20; - delivery ledger





\## Required Areas





\### 1. Persistence Adapter Boundary



Analyze mapping:



Current:



SessionDB / hermes\_state



Future:



PersistencePort



Define:



\- ownership boundary

\- transaction rules

\- generation handling

\- WAL compatibility

\- migration risks





\### 2. Delivery Adapter Boundary



Analyze:



DeliveryPort



Existing:



\- delivery ledger

\- gateway transport

\- retry handling





Define:



\- acknowledgement rules

\- duplicate prevention

\- crash recovery





\### 3. Tool Adapter Boundary



Analyze:



ToolExecutorPort



Existing:



\- tool registry

\- approval system

\- hooks





Define:



\- context propagation

\- capability boundary

\- security checks





\### 4. Provider Adapter Boundary



Analyze:



ProviderPort



Existing:



\- provider resolver

\- credentials

\- model routing





Define:



\- routing ownership

\- credential isolation

\- fallback compatibility





\### 5. Migration Sequence



Define safe order:



1\.

2\.

3\.





For every migration step specify:



\- owner before

\- owner after

\- compatibility layer

\- rollback strategy

\- validation gate





\## Create Document



Create:



docs/architecture/adapter-boundary-design.md





\## Document Structure



Must contain:





\# Adapter Boundary Design





\## 1. Current Runtime Ownership





\## 2. Adapter Principles





\## 3. Persistence Adapter





\## 4. Delivery Adapter





\## 5. Tool Adapter





\## 6. Provider Adapter





\## 7. Migration Sequence





\## 8. Rollback Strategy





\## 9. Validation Gates





\## Acceptance Criteria



✓ No production changes



✓ Existing runtime remains authoritative



✓ Adapter ownership clearly defined



✓ Migration does not bypass regression harness



✓ Rollback path documented

