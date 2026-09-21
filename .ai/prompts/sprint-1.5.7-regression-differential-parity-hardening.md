# Sprint 1.5.7 — Regression & Differential Parity Evidence Hardening

## 1. Mission

Build deterministic, isolated regression and differential-parity evidence
between the current authoritative Hermes runtime and the isolated
`hermes_core` contracts.
This sprint addresses the remaining Migration Readiness Gate evidence gaps:
- R — Legacy Regression
- P — Differential Parity
- part of B — Evidence Completeness
This sprint MUST NOT authorize or perform production migration.
The current production runtime remains authoritative.
Production migration remains:
NO-GO

---

## 2. Current verified baseline

Treat the following completed work as immutable baseline unless a real
contract defect is discovered:
- Sprint 1.5.1 — Core Contract Test Harness
- Sprint 1.5.2 — Session & Persistence Contract Hardening
- Sprint 1.5.3 — Delivery Recovery Contract Hardening
- Sprint 1.5.4 — Capability & Approval Enforcement
- Sprint 1.5.5 — Provider Routing & Fallback Hardening
- Sprint 1.5.6 — Migration Controller Implementation Hardening
Current isolated test baseline:
- `tests/hermes_core`: 126 passed
- canonical runner: 126 passed / 0 failed
Do not weaken existing contracts to make parity tests pass.

---

# 3. Hard boundary

This sprint is evidence work.
Do NOT:
- switch production ownership;
- wire `hermes_core` into production request paths;
- execute real provider calls;
- execute real tools;
- send real deliveries;
- mutate production sessions;
- write production databases;
- change production routing;
- enable migration phases;
- use production credentials;
- introduce network-dependent tests;
- introduce wall-clock-dependent tests;
- silently change legacy behavior.
All comparisons must be isolated, deterministic and side-effect free.

---

# 4. First task — inspect actual runtime

Before implementing tests, inspect the current authoritative runtime.
At minimum inspect:
- `gateway/run.py`
- `gateway/session.py`
- `hermes_state.py`
and relevant runtime modules discovered from those entry points.
Also inspect:
- `hermes_core/domain/`
- `hermes_core/application/`
- `hermes_core/ports/`
and architecture documents:
- `docs/architecture/migration-readiness-gate.md`
- `docs/architecture/regression-harness-execution.md`
- `docs/architecture/adapter-boundary-design.md`
- `docs/architecture/session-persistence-projection.md`
- `docs/architecture/delivery-recovery-contract.md`
- `docs/architecture/capability-approval-contract.md`
- `docs/architecture/provider-routing-fallback-contract.md`
- `docs/architecture/migration-controller-contract.md`
Do not assume runtime semantics from documentation alone.
For every parity claim classify evidence as:
- VERIFIED
- PARTIAL
- UNVERIFIED
If runtime behavior cannot be established safely, mark it UNVERIFIED.
Do not invent parity.

---

# 5. Define bounded parity slices

Create an explicit parity matrix.
Minimum slices:

## P1 — Session lifecycle

Compare observable semantics for:
- session creation/default state;
- lease acquisition;
- competing acquisition;
- release;
- stale release;
- close;
- stale close;
- generation progression;
- lease ownership.
Do not claim persistence parity unless actual persistence behavior was
verified.

---

## P2 — Persistence mutation outcome

Compare semantics where safely observable:
- successful mutation;
- stale writer;
- rejected domain mutation;
- persistence/infrastructure failure;
- source state preservation.
Legacy runtime may not expose identical types.
Compare semantics, not class names.

---

## P3 — Delivery outcome

Compare observable classifications for:
- confirmed success;
- confirmed failure;
- retryable metadata;
- external ID;
- transport failure;
- ambiguous/unknown acknowledgement where legacy evidence exists.
If legacy runtime cannot distinguish UNKNOWN_ACK, record this as a
semantic delta.
Do NOT force hermes_core to collapse its safer state model merely to
match legacy behavior.

---

## P4 — Tool authorization boundary

Compare:
- authorized execution;
- rejected execution;
- approval requirements;
- argument/context binding where runtime evidence exists.
If current runtime provides weaker enforcement, record a deliberate
security delta.
Do not weaken the core contract for parity.

---

## P5 — Provider routing

Compare safely observable routing inputs/outputs:
- route purpose;
- provider/model selection;
- credential reference semantics;
- candidate ordering where verifiable;
- fallback behavior where verifiable.
No real provider call.
No credential material may enter evidence.

---

## P6 — Migration control

There is no production migration-controller parity requirement because
the controller is new isolated control-plane behavior.
Instead verify:
- production runtime remains authoritative;
- no migration controller is wired into production;
- no ownership switch occurs during the harness;
- migration-controller tests remain green.
Classify production migration parity as NOT_APPLICABLE or UNVERIFIED,
not PASS.

---

# 6. Comparison model

Do not compare arbitrary Python objects directly.
Introduce a provider-neutral normalized observation model if needed.
Example conceptual form:
ParityObservation(
&#x20;   slice,
&#x20;   scenario,
&#x20;   legacy_outcome,
&#x20;   core_outcome,
&#x20;   classification,
&#x20;   reason_code,
)
Allowed classifications:
- MATCH
- INTENTIONAL_DELTA
- UNVERIFIED
- NOT_APPLICABLE
Do not introduce a generic PASS classification that hides semantic
differences.
The observation objects must contain no:
- secrets;
- credentials;
- SDK clients;
- provider clients;
- raw exceptions;
- runtime handles;
- database connections.
Prefer frozen dataclasses/value objects.

---

# 7. Legacy harness

The legacy side of the harness must be:
- read-only where possible;
- deterministic;
- isolated;
- free from production resources;
- explicit about what is simulated.
Prefer:
- existing test doubles;
- isolated constructors;
- in-memory fakes;
- pure helper calls;
- captured fixtures derived from verified behavior.
Do NOT import a production module if import itself:
- starts network activity;
- opens production storage;
- starts background workers;
- reads secrets;
- mutates global production state.
If safe isolation is impossible, mark the scenario UNVERIFIED.
Do not monkeypatch around dangerous initialization merely to claim
parity.

---

# 8. Golden fixtures

Where useful, create deterministic golden observations.
Golden fixtures must contain only normalized, non-sensitive values.
They must not contain:
- timestamps generated from wall clock;
- random UUIDs;
- credentials;
- tokens;
- host-specific paths;
- machine-specific state.
Every golden fixture must document its provenance.

---

# 9. Required regression evidence

Create a regression matrix for the authoritative runtime.
Minimum groups:
G1 — session lifecycle
G2 — session fencing/stale ownership
G3 — persistence mutation outcomes
G4 — delivery outcomes/recovery
G5 — capability/approval behavior
G6 — routing/fallback behavior
G7 — production isolation / no migration wiring
Each group must end in one of:
- VERIFIED
- PARTIAL
- UNVERIFIED
Do not convert PARTIAL or UNVERIFIED to PASS merely because a core test
exists.

---

# 10. Required differential parity scenarios

Implement deterministic tests/evidence for at least:
DP1  session initial state
DP2  successful lease acquisition
DP3  competing lease rejected/fenced
DP4  valid release
DP5  stale release
DP6  valid close
DP7  stale close
DP8  generation monotonicity
DP9  successful persistence mutation
DP10 stale persistence mutation
DP11 persistence failure preservation
DP12 delivery confirmed success
DP13 delivery confirmed failure
DP14 delivery metadata preservation
DP15 ambiguous delivery semantics
DP16 authorized tool execution
DP17 unauthorized tool execution
DP18 approval behavior
DP19 routing purpose mapping
DP20 deterministic route selection
DP21 fallback semantics
DP22 credential-reference-only evidence
DP23 migration controller remains isolated
DP24 existing hermes_core suite remains green
Additional scenarios are encouraged when actual runtime inspection
supports them.

---

# 11. Differential assertions

For each DP scenario assert:
1. legacy observation is explicit;
2. core observation is explicit;
3. classification is explicit;
4. mismatch cannot silently pass;
5. intentional delta contains a stable reason;
6. unverified behavior is not treated as parity;
7. observations contain no sensitive/runtime objects.
A test that merely asserts `True` is not evidence.
A test that checks only that a symbol exists is not sufficient parity
evidence.

---

# 12. Security deltas

Security improvements in hermes_core are allowed to differ from legacy
behavior.
Examples:
- stronger capability binding;
- stronger approval binding;
- stale generation fencing;
- unknown delivery acknowledgement;
- fail-closed routing fallback.
Classify verified stronger behavior as:
INTENTIONAL_DELTA
with an explicit reason.
Never weaken the new contract solely to produce MATCH.

---

# 13. Evidence documents

Create:
`docs/architecture/regression-differential-parity-evidence.md`
and, if useful:
`docs/architecture/differential-parity-contract.md`
The evidence document must contain:
- inspected runtime paths;
- exact test paths;
- G1–G7 matrix;
- DP1–DP24 matrix;
- MATCH / INTENTIONAL_DELTA / UNVERIFIED counts;
- known gaps;
- exact commands executed;
- exact test counts;
- production-isolation statement;
- readiness impact.
Do not record test counts before running the tests.

---

# 14. Readiness interpretation

This sprint must NOT automatically change migration readiness to GO.
At completion report separately:
R — Legacy Regression:
- VERIFIED / PARTIAL / UNVERIFIED
P — Differential Parity:
- VERIFIED / PARTIAL / UNVERIFIED
B — Evidence Completeness:
- current status
Production migration:
NO-GO
A successful isolated parity harness is evidence for future migration
work, not authorization to migrate.

---

# 15. Likely implementation scope

Prefer the smallest coherent change.
Likely files:
- `hermes_core/domain/parity.py`
- `tests/hermes_core/test_differential_parity_contract.py`
- `docs/architecture/differential-parity-contract.md`
- `docs/architecture/regression-differential-parity-evidence.md`
Only add application/port modules if genuinely required.
Do not modify production runtime solely to make it testable.
If production runtime requires modification for observation, STOP and
report the blocker.

---

# 16. Mandatory validation

Run the new parity tests directly.
Example:
python -m pytest \\
&#x20; tests/hermes_core/test_differential_parity_contract.py \\
&#x20; --confcutdir=tests/hermes_core -v
Then run the complete isolated suite:
python -m pytest \\
&#x20; tests/hermes_core \\
&#x20; --confcutdir=tests/hermes_core -v
Then:
python -m compileall hermes_core
python -c "import hermes_core; import hermes_core.domain.parity; print('parity import OK')"
Then canonical runner:
scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core
Finally inspect:
git status --short
git diff --check
git diff --stat
git diff --name-only

---

# 17. Stop conditions

STOP rather than invent semantics if:
- legacy runtime behavior cannot be safely observed;
- observation requires production credentials;
- observation requires real network/provider/tool/delivery execution;
- production mutation is required;
- a parity result depends on timing/race behavior that cannot be made
&#x20; deterministic;
- legacy behavior conflicts with documentation and cannot be resolved;
- changing production runtime is required merely to obtain evidence.
Record such cases as UNVERIFIED.

---

# 18. Completion criteria

Sprint 1.5.7 implementation is complete only when:
1. actual runtime was inspected;
2. G1–G7 are explicitly classified;
3. DP1–DP24 are explicitly classified;
4. deterministic isolated parity tests exist;
5. mismatches cannot silently pass;
6. intentional security deltas remain explicit;
7. no production resources are used;
8. no production runtime behavior is changed;
9. previous hermes_core tests remain green;
10. evidence contains actual executed results;
11. production migration remains NO-GO.
Do not commit or push implementation automatically.
Return the implementation, evidence, test results and changed-file scope
for review first.
