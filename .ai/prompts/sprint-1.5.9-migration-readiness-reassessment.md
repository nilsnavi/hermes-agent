# Sprint 1.5.9 — Migration Readiness Reassessment & Evidence Consolidation



## Role



You are acting as the senior architecture, migration-safety, and verification engineer for Hermes 2.0.



This sprint is an evidence/reassessment sprint.



Do NOT implement production migration.

Do NOT wire hermes_core into the existing runtime.

Do NOT transfer runtime ownership.

Do NOT enable shadow traffic, canary traffic, cutover, failover, or production adapters.



The existing Hermes runtime remains authoritative.



Production migration remains NO-GO unless a future explicitly approved sprint changes that decision.



---



# 1. Mission



Reassess the original Hermes 2.0 Migration Readiness Gate after the completed isolated contract-hardening work from Sprint 1.5.1 through Sprint 1.5.8.



The objective is to answer precisely:



1. Which original readiness gates are now verified?

2. Which are only partially addressed?

3. Which remain unverified or failed?

4. Which original blockers B1-B7 have been reduced, transformed, or closed?

5. What concrete evidence supports every status?

6. What is the smallest safe next engineering slice?

7. What must still happen before any production shadow/canary/cutover work can be authorized?



This sprint must consolidate existing evidence rather than fabricate readiness.



---



# 2. Baseline



Use the actual repository state and inspect the implementation.



Completed evidence baseline includes:



Sprint 1.5.1:

Core Contract Test Harness.



Sprint 1.5.2:

Session & Persistence Contract Hardening.



Sprint 1.5.3:

Delivery Recovery Contract Hardening.



Sprint 1.5.4:

Capability & Approval Enforcement.



Sprint 1.5.5:

Provider Routing & Fallback Contract Hardening.



Sprint 1.5.6:

Migration Controller Implementation Hardening.



Sprint 1.5.7:

Regression & Differential Parity Evidence Hardening.



Sprint 1.5.8:

Lifecycle / Recovery / Rollback Evidence Hardening.



Current isolated hermes_core baseline:



182 tests passing.



Do not trust this number blindly.

Re-run the final canonical suite and record the actual result.



---



# 3. Hard safety boundary



This sprint is READ-ONLY with respect to production runtime behavior.



Allowed:



- inspect source

- inspect tests

- inspect architecture documents

- add/update architecture evidence documents

- add evidence-only tests if absolutely necessary to prove an existing contract

- correct stale documentation

- execute isolated tests

- execute existing legacy regression tests if safe and available

- inspect runtime code without modifying its behavior



Forbidden:



- production runtime wiring

- SessionDB migration

- real DB writes

- production SQLite/WAL modification

- provider calls

- real tool execution

- real delivery

- network effects

- credential access

- traffic switching

- feature flags that affect production

- shadow/canary/cutover activation

- migration ownership transfer

- adapter activation

- destructive schema changes



If reassessment requires any forbidden mutation:

STOP and classify that evidence as UNVERIFIED.



---



# 4. Inspect the original readiness gate



Read:



docs/architecture/migration-readiness-gate.md



Do not replace its gate model.



Reassess the same gate categories:



A — Architecture contracts

C — Core contracts

R — Legacy regression

P — Differential parity

L — Lifecycle / recovery / rollback

S — Security / capability enforcement

M — Performance

B — Evidence completeness



Allowed final status vocabulary:



PASS

PARTIAL

FAIL

UNVERIFIED



Do not invent alternative readiness labels.



---



# 5. Reassess original blockers B1-B7



The original blockers were:



B1 — Session mutation not transactionally fenced



B2 — Persistence projection incomplete



B3 — Delivery outcome cannot preserve current recovery semantics



B4 — Capability/approval not enforced by core



B5 — Provider routing contract does not own existing behavior



B6 — Migration controller architecture only / not implemented



B7 — Regression/rollback evidence incomplete



For every blocker determine:



OPEN

PARTIALLY_ADDRESSED

CLOSED_AT_CORE_CONTRACT_LEVEL



These blocker labels are separate from readiness gate statuses.



Never use CLOSED_AT_CORE_CONTRACT_LEVEL to imply production readiness.



For each blocker include:



- original problem

- work completed

- exact files/contracts/tests providing evidence

- remaining gap

- production consequence

- recommended next action



---



# 6. Required reassessment logic



## Gate A — Architecture contracts



Inspect at minimum:



docs/architecture/adapter-boundary-design.md

docs/architecture/capability-policy-contract.md

docs/architecture/runtime-migration-controller.md

docs/architecture/migration-controller-contract.md

docs/architecture/session-persistence-projection.md

docs/architecture/delivery-recovery-contract.md

docs/architecture/provider-routing-fallback-contract.md

docs/architecture/lifecycle-recovery-rollback-contract.md



Verify consistency between documents and actual hermes_core contracts.



A may be PASS only if the isolated architecture contracts are mutually consistent and material contradictions are resolved.



Production implementation absence alone does not necessarily make A fail if A is explicitly architecture-contract readiness.



Document the exact interpretation.



---



## Gate C — Core contracts



Use executable evidence from:



tests/hermes_core/



At minimum cover:



session

persistence

delivery

capability/approval

routing/fallback

migration controller

lifecycle/recovery/rollback



Re-run the canonical hermes_core suite.



C may be PASS for isolated core contracts if all required core invariants are executable and green.



Do not claim runtime integration from C.



---



## Gate R — Legacy regression



Inspect the existing legacy/runtime test infrastructure.



Use the original regression harness requirements.



Determine:



- what legacy regression suite exists

- whether it can be safely executed

- what G1-G7 evidence actually exists

- what remains missing



Run existing safe regression tests where possible.



Do not create fake legacy evidence.



If only partial legacy evidence exists:

R = PARTIAL.



---



## Gate P — Differential parity



Use Sprint 1.5.7 evidence.



Inspect:



docs/architecture/differential-parity-contract.md

docs/architecture/regression-differential-parity-evidence.md

tests/hermes_core/test_differential_parity_contract.py



Do not convert UNVERIFIED observations into MATCH.



Report actual totals:



MATCH

INTENTIONAL_DELTA

UNVERIFIED

NOT_APPLICABLE



If legacy execution is still unavailable for most observations:

P must remain PARTIAL or UNVERIFIED according to the actual gate definition.



---



## Gate L — Lifecycle / recovery / rollback



Use Sprint 1.5.8 evidence.



Inspect:



docs/architecture/lifecycle-recovery-rollback-contract.md

docs/architecture/lifecycle-recovery-rollback-evidence.md

tests/hermes_core/test_lifecycle_recovery_contract.py



Consider:



LR1-LR24

SR1-SR6

DR1-DR6

rollback rehearsal

kill switch

failover



Explicitly distinguish:



isolated control-plane lifecycle evidence



from:



operational runtime recovery evidence.



SR6 remains UNVERIFIED unless actual repository evidence proves otherwise.



Durable audit persistence and runtime ownership execution must not be inferred.



---



## Gate S — Security / capability enforcement



Use Sprint 1.5.4 evidence.



Inspect:



hermes_core/domain/capability.py

hermes_core/application/execution_service.py

tests/hermes_core/test_capability_approval_contract.py

docs/architecture/capability-policy-contract.md



Determine what is now enforced in core and what is still adapter/runtime-owned.



Check whether the original S failure can now move to PARTIAL or PASS at core-contract scope.



Do not call production security PASS if runtime adapters can still bypass core enforcement.



---



## Gate M — Performance



Do not infer performance readiness from unit test speed.



Look for actual:



- latency baselines

- throughput baselines

- memory baselines

- provider overhead

- persistence overhead

- migration controller overhead

- regression performance thresholds



If no representative benchmark exists:

M = UNVERIFIED.



Unit test duration is not a production performance benchmark.



---



## Gate B — Evidence completeness



Evaluate whether evidence exists for all other gates.



Evidence completeness must consider:



- reproducible commands

- exact test counts

- contract docs

- regression receipts

- parity receipts

- lifecycle rehearsal

- security evidence

- performance evidence

- rollback evidence

- production isolation

- remaining gaps



B cannot PASS while material gates remain unsupported by required evidence.



---



# 7. Production migration phase reassessment



Revisit the migration phases from the original readiness gate.



At minimum classify authorization for:



Phase 0 — offline / isolated validation

Phase 1 — detached/read-only shadow

Phase 2 — bounded shadow comparison

Phase 3 — canary ownership

Phase 4 — production cutover



For every phase use:



AUTHORIZED

NOT_AUTHORIZED



Do not authorize a phase merely because its core contract exists.



For every phase provide:



- prerequisites

- current evidence

- missing evidence

- safety reason



Expected conservative baseline:



Phase 0 may be AUTHORIZED.



Do not assume Phase 1+.



Derive from evidence.



---



# 8. Determine the smallest safe next engineering slice



This is a critical output.



Based on remaining blockers, identify exactly ONE recommended next implementation slice.



The slice must:



- be bounded

- be reversible

- avoid production ownership transfer

- avoid real provider/tool/delivery effects

- have explicit entry/exit criteria

- produce evidence needed by one or more remaining gates



Candidate examples include:



- detached read-only session projection adapter

- offline legacy-vs-core projection parity harness

- regression harness completion

- benchmark harness

- durable migration-controller state prototype



Do not choose based on convenience.



Choose based on the evidence gap with the highest migration-safety value.



Do NOT implement the slice in Sprint 1.5.9.



Only define it.



---



# 9. Required output document



Create:



docs/architecture/migration-readiness-reassessment.md



It must contain:



## Executive summary



## Baseline inspected



## Canonical validation result



## Gate reassessment



Table:



| Gate | Previous | Current | Evidence | Remaining gap |



for:



A

C

R

P

L

S

M

B



## Blocker reassessment



Table:



| Blocker | Previous | Current | Evidence | Remaining gap | Next action |



for:



B1-B7



## Differential parity summary



MATCH:

INTENTIONAL_DELTA:

UNVERIFIED:

NOT_APPLICABLE:



## Lifecycle/recovery summary



LR:

SR:

DR:

rollback:

kill switch:

failover:

operational gaps:



## Security summary



## Performance summary



## Production phase authorization



Phase 0 through Phase 4.



## Smallest safe next engineering slice



Include:



scope

non-goals

entry criteria

implementation boundary

test/evidence requirements

rollback/isolation requirements

exit criteria



## Remaining migration blockers



## Final readiness conclusion



The conclusion must explicitly state whether production migration remains NO-GO.



---



# 10. Optional machine-readable snapshot



If useful, create:



docs/architecture/migration-readiness-reassessment.json



Only if it adds value.



If created, it must contain no secrets and must match the Markdown document exactly.



Do not create it merely for volume.



---



# 11. Evidence quality rules



Every PASS must have executable or inspectable evidence.



Every PARTIAL must state exactly what is verified and what is missing.



Every UNVERIFIED must state what evidence is absent.



Every FAIL must state the violated requirement.



Do not upgrade a gate because a document says it is ready.



Tests prove only what they execute.



Architecture documents prove only contract definition, not runtime behavior.



Unit tests do not prove production integration.



No synthetic parity.



No fabricated regression receipts.



No inferred benchmark results.



---



# 12. Required validation



Run:



python -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q



python -m compileall hermes_core



Canonical Windows runner:



& 'C:\\Program Files\\Git\\bin\\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Python314/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'



Also run any safe existing legacy regression command discovered during inspection.



Record exact command and exact result.



Then:



git status --short

git diff --check

git diff --stat

git diff --name-only



---



# 13. Stop conditions



STOP rather than fabricate evidence if:



- production runtime modification is required

- production DB access is required

- network/provider/tool/delivery effects are required

- credentials are required

- representative legacy execution cannot be performed safely

- performance cannot be measured representatively

- a gate cannot be verified from available evidence

- contradictory evidence cannot be resolved without runtime mutation



Use UNVERIFIED/PARTIAL.



That is a valid outcome.



---



# 14. Completion criteria



Sprint 1.5.9 is complete only if:



1. Original migration-readiness gate was inspected.

2. Sprints 1.5.1-1.5.8 evidence was inspected.

3. A/C/R/P/L/S/M/B were reassessed.

4. Every gate has explicit evidence.

5. B1-B7 were reassessed.

6. No blocker is silently discarded.

7. Differential parity totals are preserved accurately.

8. Lifecycle evidence distinguishes isolated vs operational recovery.

9. Security distinguishes core enforcement vs runtime enforcement.

10. Performance is not inferred from unit-test speed.

11. Production phases 0-4 are explicitly authorized/not authorized.

12. Exactly one smallest safe next engineering slice is identified.

13. Canonical hermes_core suite passes.

14. Actual test counts are recorded.

15. Legacy regression is executed if safely available, otherwise explicitly marked.

16. No production effects occurred.

17. Production migration decision is explicit.

18. Evidence document is internally consistent.

19. git diff --check passes.

20. No implementation of the next migration slice is performed.



---



# 15. Final response



Return:



1. files inspected

2. files changed

3. canonical test result

4. legacy regression result

5. gate table A/C/R/P/L/S/M/B

6. blocker table B1-B7

7. phase authorization 0-4

8. smallest safe next engineering slice

9. remaining gaps

10. final production migration decision



Do NOT commit.

Do NOT push.
