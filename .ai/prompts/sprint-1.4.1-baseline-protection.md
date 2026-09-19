\# Hermes 2.0 — Sprint 1.4.1 Baseline Protection





\## Role



You are Hermes Architecture Validation Agent.





\## Goal



Create a behavioral baseline before runtime refactoring.



This phase protects existing Hermes behavior.



The purpose is not optimization.



The purpose is to understand:



\- what must not break;

\- what contracts exist;

\- what tests are required before migration.





\---



\# Mode



Analysis + test planning only.





\---



\# Restrictions



DO NOT:



\- modify production code;

\- refactor modules;

\- move files;

\- change APIs;

\- change database schema;

\- change runtime behavior.





Only create documentation.





\---



\# Analyze





\## 1. Session Lifecycle





Analyze:





\- session creation;

\- session restoration;

\- session closing;

\- resume behavior;

\- session ownership;

\- concurrent sessions.





Document:





\- current implementation;

\- invariants;

\- risks.





\---



\## 2. State Persistence





Analyze:





\- hermes\_state.py

\- hermes\_state\_common.py

\- hermes\_state\_dbfile.py





Document:





\- SQLite lifecycle;

\- WAL handling;

\- migrations;

\- generation tracking;

\- recovery mechanisms.





Identify:



\- what must remain unchanged during refactoring.





\---



\## 3. Runtime Lifecycle





Analyze:





\- gateway startup;

\- shutdown;

\- background workers;

\- cron;

\- delivery recovery.





Document:





\- startup sequence;

\- shutdown sequence;

\- ownership boundaries.





\---



\## 4. Tool Execution





Analyze:





\- tool registration;

\- tool discovery;

\- execution pipeline;

\- approval checks;

\- capability checks.





Document:





\- current flow;

\- security assumptions.





\---



\## 5. Provider Routing





Analyze:





\- model selection;

\- provider fallback;

\- credentials;

\- configuration precedence.





Document:





\- routing rules;

\- fallback behavior;

\- possible regressions.





\---



\# Required Output





Create:





docs/architecture/baseline-protection-plan.md





The document must contain:





\## 1. Current Behavior Map





\## 2. Critical Runtime Invariants





\## 3. Required Regression Tests





\## 4. Migration Safety Gates





\## 5. Rollback Strategy





\## 6. High Risk Areas





\---



\# Read Before Analysis





Read and respect:





\- AGENTS.md

\- SECURITY.md

\- docs/architecture/runtime-audit.md

\- evals/





\---



\# Acceptance Criteria





✓ No production code changes



✓ No API changes



✓ Only documentation created



✓ Existing behavior preserved



✓ Migration risks documented

