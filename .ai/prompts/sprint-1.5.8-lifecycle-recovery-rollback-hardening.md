\# Sprint 1.5.8 — Lifecycle / Recovery / Rollback Evidence Hardening



\## 1. Mission



Implement deterministic, isolated lifecycle, recovery, and rollback evidence for Hermes 2.0.



This sprint addresses the Migration Readiness Gate:



\- L — Lifecycle / recovery / rollback

\- part of B — Evidence completeness



The sprint MUST NOT authorize production migration.



Production migration remains:



NO-GO



The current production runtime remains authoritative.



The purpose of this sprint is to prove, in isolation, that Hermes migration lifecycle transitions, recovery behavior, rollback behavior, stale-owner fencing, and failure preservation are explicit, deterministic, and fail-closed.



\---



\## 2. Baseline



Treat the completed Sprint 1.5.x contracts as the baseline.



Expected baseline includes:



\- Sprint 1.5.1 — Core Contract Test Harness

\- Sprint 1.5.2 — Session \& Persistence Contract Hardening

\- Sprint 1.5.3 — Delivery Recovery Contract Hardening

\- Sprint 1.5.4 — Capability \& Approval Enforcement

\- Sprint 1.5.5 — Provider Routing \& Fallback Hardening

\- Sprint 1.5.6 — Migration Controller Implementation Hardening

\- Sprint 1.5.7 — Regression \& Differential Parity Evidence Hardening



Current isolated hermes\_core suite baseline:



152 tests passed

0 failed



Do not weaken or rewrite existing contracts merely to make lifecycle tests pass.



If an existing contract prevents a required safe lifecycle behavior, report the conflict before changing the contract.



\---



\## 3. Hard boundary



This sprint is isolated contract/evidence work only.



DO NOT:



\- switch production ownership

\- wire MigrationController into production runtime

\- modify production session ownership

\- modify production routing

\- invoke real providers

\- invoke real tools

\- perform real deliveries

\- access production databases

\- use real credentials

\- use network resources

\- introduce production migration flags

\- activate SHADOW/CANARY/CUTOVER in production

\- create a production kill switch

\- modify runtime behavior merely to make a test observable

\- claim rollback readiness without executed evidence



Production runtime must remain unchanged.



If a required test needs production mutation, STOP and report the blocker.



\---



\## 4. Inspect actual contracts first



Before implementation, inspect:



\### Migration



\- `hermes\_core/domain/migration.py`

\- `tests/hermes\_core/test\_migration\_controller\_contract.py`

\- `docs/architecture/migration-controller-contract.md`

\- `docs/architecture/migration-controller-hardening-evidence.md`



\### Session / persistence



\- `hermes\_core/domain/session.py`

\- `hermes\_core/application/session\_service.py`

\- `hermes\_core/ports/persistence.py`

\- `tests/hermes\_core/test\_session\_contract.py`

\- `tests/hermes\_core/test\_session\_persistence\_hardening.py`



\### Delivery recovery



\- `hermes\_core/domain/delivery.py`

\- `hermes\_core/application/delivery\_service.py`

\- `tests/hermes\_core/test\_delivery\_recovery\_contract.py`



\### Capability / routing



Inspect existing hardened contracts where lifecycle ownership or rollback may interact with them.



\### Readiness / parity



\- `docs/architecture/migration-readiness-gate.md`

\- `docs/architecture/regression-differential-parity-evidence.md`

\- `docs/architecture/differential-parity-contract.md`



Also inspect the production runtime paths identified by Sprint 1.5.7.



Do not infer runtime behavior from architecture documentation alone.



Classify observations as:



\- VERIFIED

\- PARTIAL

\- UNVERIFIED

\- NOT\_APPLICABLE



\---



\# 5. Lifecycle model



The lifecycle evidence must use the existing migration controller contract.



Expected phases:



\- OFF

\- SHADOW

\- CANARY

\- DRAINING

\- CUTOVER

\- ROLLBACK



Expected owners:



\- LEGACY

\- HERMES\_CORE



Expected drain states:



\- NOT\_DRAINING

\- DRAIN\_REQUESTED

\- DRAINED



Do not silently introduce another lifecycle model.



If implementation and documentation disagree, document the discrepancy and resolve the documentation unless the implementation violates a safety invariant.



\---



\# 6. Critical lifecycle invariants



The following invariants must be explicitly tested.



\## L1 — Initial ownership



Initial state must be safe.



Expected:



phase = OFF

owner = LEGACY



No candidate may implicitly own production work.



\---



\## L2 — Explicit transitions only



No phase transition may occur unless it exists in the legal transition graph.



Illegal transitions must fail closed.



State must remain unchanged.



\---



\## L3 — Generation fencing



Every mutating lifecycle operation must be fenced by expected generation.



A stale controller request must never mutate current state.



\---



\## L4 — Scope fencing



A transition request for one migration scope must not mutate another scope.



Scope mismatch must fail closed.



\---



\## L5 — Shadow ownership



SHADOW must not transfer authoritative ownership.



Expected authoritative owner:



LEGACY



\---



\## L6 — Canary ownership



CANARY must not silently transfer authoritative ownership unless the existing contract explicitly defines otherwise.



Document the exact existing behavior.



Do not invent production semantics.



\---



\## L7 — Drain required before cutover



CUTOVER must not succeed before the scope is fully drained.



Expected progression:



NOT\_DRAINING

→ DRAIN\_REQUESTED

→ DRAINED

→ CUTOVER



Attempting CUTOVER before DRAINED must fail closed.



\---



\## L8 — Cutover ownership



Successful isolated CUTOVER must explicitly transfer ownership according to the existing migration contract.



The test must prove:



\- phase

\- owner

\- candidate owner

\- generation

\- drain state



Do not equate isolated CUTOVER contract success with production migration authorization.



\---



\## L9 — Rollback availability



Rollback must be explicitly available from every phase where the existing contract permits it.



At minimum inspect:



\- CANARY

\- DRAINING

\- CUTOVER



\---



\## L10 — Rollback restores safe owner



Rollback from a transferred-owner state must restore the previous safe authoritative owner according to the existing contract.



For the current contract this is expected to restore:



LEGACY



Do not hardcode this assumption without first verifying the current implementation.



\---



\## L11 — Stale rollback rejected



A rollback request using stale generation must fail closed.



It must not mutate:



\- phase

\- owner

\- candidate owner

\- drain state

\- scope

\- previous owner



\---



\## L12 — Wrong-scope rollback rejected



Rollback for another migration scope must not mutate the active scope.



\---



\## L13 — Kill switch



Verify existing kill-switch behavior.



The kill switch must prevent unsafe forward lifecycle progression according to the current contract.



Test:



\- enable

\- repeated enable

\- mutation while enabled

\- disable

\- stale enable/disable

\- generation behavior



Do not claim production kill-switch readiness.



This is isolated controller evidence only.



\---



\## L14 — Failure atomicity



A rejected lifecycle operation must leave source state unchanged.



This applies to:



\- stale generation

\- wrong scope

\- illegal transition

\- drain violation

\- kill-switch rejection

\- unsupported failover



\---



\## L15 — Audit determinism



Every lifecycle operation must produce deterministic audit evidence according to the existing controller contract.



Audit evidence must not contain:



\- credentials

\- secrets

\- SDK clients

\- DB connections

\- runtime handles

\- arbitrary exception objects



\---



\# 7. Recovery model



Recovery evidence must distinguish:



1\. known safe retry

2\. stale request

3\. rejected transition

4\. persistence failure

5\. ambiguous delivery outcome

6\. rollback

7\. failover



Do not treat these as equivalent.



\---



\# 8. Session recovery



Use the hardened session/persistence contracts.



Test recovery semantics for:



\### SR1



Persistence failure during lease acquisition.



Source object must remain unchanged.



\### SR2



CAS conflict from stale session projection.



Current durable state must win.



\### SR3



Persistence failure during lease release.



Source object must not falsely reflect successful release.



\### SR4



Persistence failure during close.



Source object must not falsely become closed.



\### SR5



Stale owner recovery attempt.



Must be rejected.



\### SR6



Successful retry after a recoverable persistence failure.



Only implement this if the current contract supports it deterministically.



Otherwise classify as UNVERIFIED.



Do not invent retry policy.



\---



\# 9. Delivery recovery



Reuse the existing delivery recovery contract.



Test lifecycle evidence for:



\### DR1



CONFIRMED\_SUCCESS is terminal delivered behavior.



\### DR2



CONFIRMED\_FAILURE follows the existing failure contract.



\### DR3



UNKNOWN\_ACK must not automatically become retry-safe.



\### DR4



Explicit reconciliation from UNKNOWN\_ACK.



\### DR5



Explicit abandonment from UNKNOWN\_ACK where supported.



\### DR6



Generic unexpected exceptions must not be silently converted into safe retry semantics.



Do not perform real delivery.



\---



\# 10. Migration rollback rehearsal



Implement an isolated rollback rehearsal.



It must execute the lifecycle rather than merely asserting enum values.



Expected rehearsal:



OFF

→ SHADOW

→ CANARY

→ DRAINING

→ DRAIN\_REQUESTED

→ DRAINED

→ CUTOVER

→ ROLLBACK

→ OFF



Use the exact legal API exposed by the current MigrationController.



Do not modify the controller simply to force this sequence if the existing legal graph differs.



If the actual graph differs:



1\. document the real graph

2\. execute the legal equivalent

3\. explain the difference



The rehearsal must capture state after every step.



\---



\# 11. Rollback rehearsal evidence



Introduce a normalized, immutable representation if useful.



Example:



```python

@dataclass(frozen=True)

class LifecycleObservation:

&#x20;   step: str

&#x20;   phase: str

&#x20;   owner: str

&#x20;   candidate\_owner: str | None

&#x20;   generation: int

&#x20;   drain\_state: str

&#x20;   result\_status: str

