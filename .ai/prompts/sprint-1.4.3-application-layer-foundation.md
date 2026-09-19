\# Hermes 2.0 — Sprint 1.4.3 Application Layer Foundation





\## Role



You are Hermes Application Architecture Agent.





\## Mission



Create the first Application Layer foundation for Hermes 2.0.



This task creates architectural boundaries only.



Existing runtime behavior must remain unchanged.





\---



\# Objective



Introduce clean application boundaries:





RuntimeApplication



SessionService



ExecutionService



DeliveryService



ProviderRouter







The goal is dependency direction, not migration.





\---



\# Mode



Implementation with strict isolation.





\---



\# Restrictions





DO NOT:



\- modify gateway behavior;

\- replace existing runtime;

\- move existing classes;

\- delete code;

\- change APIs;

\- change database schema;

\- change provider behavior;

\- modify existing workflows.





Only create new isolated architecture layer.





\---



\# Required Structure





Create:





hermes\_core/





\## application/





Create:





runtime\_application.py



session\_service.py



execution\_service.py



delivery\_service.py



provider\_router.py







\## domain/





Create:





session.py



delivery.py



routing.py







\## ports/





Create:





persistence.py



delivery.py



providers.py



tools.py







\---



\# Design Requirements





\## Application Layer





Application services own:



\- orchestration;

\- business workflows;

\- state transitions;

\- policies.





Application services DO NOT:



\- access SQLite directly;

\- import gateway modules;

\- import provider SDKs;

\- access environment variables directly.







\---



\# SessionService





Define responsibility:





\- session lifecycle;

\- create;

\- resume;

\- close;

\- lease ownership;

\- generation tracking.





No storage implementation.





Use:



SessionRepository port.





\---



\# ProviderRouter





Define:





RouteDecision





with:





\- provider

\- model

\- endpoint

\- api\_mode

\- credential\_reference

\- route\_purpose





No provider SDK calls.





\---



\# ExecutionService





Define:





\- tool invocation contract;

\- approval boundary;

\- capability check boundary;

\- result handling.





No subprocess execution.





\---



\# DeliveryService





Define:





DeliveryState:





pending



attempting



delivered



failed





No transport implementation.





\---



\# RuntimeApplication





Define orchestration:





incoming event



↓



session ownership



↓



provider route



↓



execution



↓



persistence



↓



delivery







Only interfaces.





\---



\# Ports





Create Protocol/interfaces:





PersistencePort



DeliveryPort



ProviderPort



ToolExecutorPort





\---



\# Documentation





Create:





docs/architecture/application-layer-foundation.md





Document:





1\. New layers



2\. Dependency rules



3\. Current runtime compatibility



4\. Future migration path





\---



\# Testing





Add only architecture validation tests if required.



Do not migrate existing tests.





\---



\# Acceptance Criteria





✓ Existing runtime unchanged



✓ New layer compiles/imports



✓ No circular dependencies



✓ No infrastructure imports in domain/application



✓ Architecture documentation created



✓ Existing tests remain green

