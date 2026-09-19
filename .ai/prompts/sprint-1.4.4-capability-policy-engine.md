\# Hermes 2.0 — Sprint 1.4.4 Capability Policy Engine





\## Role



You are Hermes Capability Security Architecture Agent.





\## Mission



Design capability authorization layer before runtime migration.



This sprint defines policy contracts only.



No runtime integration.





\---



\# Mode



Architecture analysis + contract design.



No implementation.





\---



\# Restrictions



DO NOT:



\- modify production code;

\- modify existing tests;

\- connect hermes\_core to runtime;

\- change tool registry;

\- change provider resolver;

\- change approval implementation;

\- create database migrations.





Only create architecture documentation.





\---



\# Analyze Existing Security Boundaries





Study:



\- tools/

\- agent/

\- gateway/

\- hermes\_state\*

\- SECURITY.md

\- AGENTS.md

\- docs/architecture/runtime-audit.md

\- docs/architecture/adapter-boundary-design.md





\---



\# Required Analysis Areas





\## 1. Capability Model





Define:



\- capability identity

\- capability scope

\- capability ownership

\- capability lifetime

\- capability expiration





Questions:



Who grants capability?



Who validates capability?



Who can revoke capability?





\---



\## 2. Tool Authorization





Analyze:



\- tool calls

\- approval flow

\- hooks

\- permissions

\- execution context





Define:



Policy decision:



ALLOW



DENY



REQUIRE\_APPROVAL





\---



\## 3. Provider Authorization





Analyze:



\- model routing

\- provider access

\- credentials

\- secret references





Define:



\- provider capability

\- model capability

\- credential boundary





\---



\## 4. Execution Context





Define immutable policy input:



session



user



agent



tool



capability



approval



risk level





\---



\# Create Document





Create:



docs/architecture/capability-policy-engine.md





Document must contain:





\## 1. Current Authorization Landscape



\## 2. Capability Model



\## 3. Policy Decision Contract



\## 4. Tool Authorization Rules



\## 5. Provider Authorization Rules



\## 6. Migration Boundaries



\## 7. Security Risks





\---



\# Required Format





For each capability:





Capability:



Owner:



Input context:



Decision:



Enforcement point:



Risk:





\---



\# Acceptance Criteria





✓ No code changes



✓ Existing runtime remains authoritative



✓ Capability model documented



✓ Policy contract defined



✓ Migration risks identified

