\# Hermes 2.0 — Sprint 1.4.3.1 Contract Hardening





\## Role



You are Hermes Domain Contract Hardening Agent.





\## Mission



Improve hermes\_core contracts before runtime migration.



This task strengthens domain models and ports.



Existing Hermes runtime must remain unchanged.





\---



\# Mode



Implementation inside hermes\_core only.





\---



\# Restrictions





DO NOT:



\- modify gateway;

\- modify hermes\_state;

\- modify CLI;

\- connect new services to old runtime;

\- change existing APIs;

\- migrate existing code.





Allowed:



\- modify hermes\_core only;

\- add domain value objects;

\- improve ports;

\- improve type safety.





\---



\# Scope





\## 1. Session Contract





File:



hermes\_core/domain/session.py





Requirements:





Separate:





session generation



and





lease generation







Add:





lease\_generation: int





Rules:





generation:



\- represents session state version





lease\_generation:



\- represents ownership version





Improve:





close()





It must require ownership validation:





close(owner, generation)





Stale owners must not close active sessions.





\---



\# 2. Delivery Contract





File:



hermes\_core/domain/delivery.py





Add:





DeliveryResult





with:





success: bool



external\_id: str | None



retryable: bool



error: str | None







Use immutable dataclass where appropriate.





\---



\# 3. Tool Execution Contract





File:



hermes\_core/ports/tools.py





Replace simple approval flag model.





Create:





ToolExecutionContext





Fields:





session\_id



turn\_id



tool\_call\_id



capability\_grant



approved







ToolExecutorPort must accept execution context.





\---



\# 4. Provider Routing Contract





File:



hermes\_core/domain/routing.py





Ensure:





RouteDecision





is immutable.





Use:





@dataclass(frozen=True)







Required fields:





provider



model



endpoint



api\_mode



credential\_reference



purpose







\---



\# 5. Validation





Run:





python -m compileall hermes\_core





python -c "import hermes\_core"





Verify:





No imports from:





gateway



hermes\_state



sqlite



provider SDKs







\---



\# Documentation





Update:





docs/architecture/application-layer-foundation.md





Add:





\- hardened contracts

\- concurrency assumptions

\- future migration notes







\---



\# Acceptance Criteria





✓ Only hermes\_core changed



✓ Existing runtime unchanged



✓ Domain contracts improved



✓ Imports successful



✓ No circular dependencies



✓ Documentation updated

