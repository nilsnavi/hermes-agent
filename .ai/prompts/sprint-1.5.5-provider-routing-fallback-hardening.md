# Sprint 1.5.5 — Provider Routing & Fallback Contract Hardening

## Role

You are the Hermes Provider Routing & Fallback Contract Architecture Agent.

Your task is to harden the isolated `hermes_core` provider-routing contract so that future runtime adapters can reproduce Hermes routing, credential selection, fallback and recovery behavior without moving production ownership into `hermes_core`.

This sprint addresses Migration Readiness Gate blocker B5.

The existing production Hermes runtime remains authoritative.

This sprint MUST NOT migrate production provider routing, provider clients, credential storage, fallback ownership, prompt-cache implementation, or runtime traffic to `hermes_core`.

Do not commit.
Do not push.

---

# 1. Context

Previous hardening established:

- Sprint 1.5.1 — isolated core contract harness;
- Sprint 1.5.2 — session/persistence CAS contracts;
- Sprint 1.5.3 — delivery/recovery contracts;
- Sprint 1.5.4 — capability/approval enforcement contracts.

The current provider-routing core contract remains intentionally minimal.

Existing isolated routing contracts establish approximately:

- provider-neutral `RouteDecision`;
- opaque credential references;
- immutable routing value objects;
- delegation of routing inputs through the router port/application boundary.

This is insufficient for production migration.

Migration Readiness Gate blocker B5 identified missing or insufficiently proven behavior around:

- routing precedence;
- main versus auxiliary/model-purpose routing;
- credential selection;
- credential-pool recovery;
- fallback ordering;
- retry/fallback ownership;
- provider failure classification;
- prompt-cache-sensitive routing behavior;
- credential lifecycle;
- profile/session scope;
- compatibility with current production runtime behavior.

The core must not invent production behavior where repository evidence is absent.

---

# 2. Sprint objective

Create an explicit provider-neutral routing contract that can answer:

1. What routing purpose is being requested?
2. Which provider/model candidate is selected?
3. Why was that candidate selected?
4. Which opaque credential reference is associated with it?
5. What deterministic precedence produced the selection?
6. Which fallback candidates are legal?
7. Which failures permit fallback?
8. Which failures must stop routing?
9. Who owns retry versus fallback?
10. How are exhausted candidates represented?
11. How is credential unavailability represented?
12. Which routing information belongs to core versus adapters/runtime?
13. Which current production semantics are VERIFIED, PARTIAL or UNVERIFIED?

The contract must be deterministic and provider-neutral.

---

# 3. Architecture constraints

Preserve dependency direction:

    domain
      ↑
    application
      ↑
    ports
      ↑
    future adapters/runtime

Do not import into `hermes_core` provider SDKs, provider HTTP clients, production credential stores, environment credential loaders, database implementations, production model registries, runtime gateway objects, or provider-specific exception classes.

No network.
No database.
No subprocess.
No sleeps.
No credentials.
No real provider calls.

Use immutable provider-neutral value objects.

---

# 4. Runtime inspection — mandatory

Before changing the core contract, inspect the authoritative production runtime.

Locate actual repository paths responsible for:

- provider/model routing;
- main model selection;
- auxiliary model selection;
- routing purpose;
- profile-level routing;
- session-level routing/home provider if present;
- provider/model precedence;
- credential selection and pools;
- credential failure/recovery;
- provider/model fallback;
- retry ownership;
- provider error classification;
- rate-limit/auth/transient/permanent failure handling;
- prompt-cache behavior and routing affinity;
- provider health/cooldown if any;
- audit/logging of routing decisions.

For every observed behavior classify evidence as VERIFIED, PARTIAL, or UNVERIFIED.

Record exact file/path evidence. Do not infer unsupported production behavior. Do not modify production runtime paths.

---

# 5. Route purpose contract

Inspect the current core and production runtime before changing names.

The existing core has `RoutePurpose` / `route_purpose` semantics. Preserve existing supported values unless repository evidence justifies an intentional extension.

Determine whether production distinguishes main conversation/model execution, auxiliary model execution, title generation, memory/query rewrite, compression, tool-related model calls, or other special-purpose calls.

Do not invent purposes solely for architectural neatness. If runtime purpose mapping is incomplete, preserve a conservative core representation and document the gap.

---

# 6. Routing request

Create or harden an immutable provider-neutral routing request/value object if useful.

It should carry only routing-relevant identity/context, such as route purpose, requested model/model class where supported, profile/session routing references where supported, required capabilities where evidenced, and cache/affinity hints where evidenced.

Do not put secrets, API keys, SDK clients, mutable provider objects, or HTTP sessions inside the routing request.

---

# 7. Route candidate

Represent a possible provider/model route explicitly if required.

A provider-neutral candidate may include provider identifier, model identifier, opaque credential reference, route purpose, precedence/rank, and opaque non-secret adapter metadata.

The core must never contain actual credentials. Credential references remain opaque identifiers. A candidate is not equivalent to successful provider execution.

---

# 8. Route decision

Harden `RouteDecision` while preserving existing valid contracts.

The decision must be immutable and make clear selected provider/model, route purpose, opaque credential reference, selection precedence/reason where appropriate, and fallback availability if that belongs in the contract.

Do not expose secrets or attach SDK clients. Do not claim provider availability merely because a route was selected.

---

# 9. Deterministic precedence

Routing precedence must be explicit and deterministic. Inspect production behavior first.

Potential sources may include explicit request override, session affinity/home, profile configuration, purpose-specific configuration, configured default, and fallback chain — only where evidenced.

Do not use this example ordering as production truth.

Given the same routing inputs and candidate availability/evidence, candidate ordering must be deterministic. Dictionary iteration accident or provider SDK ordering must not determine routing.

---

# 10. Fallback contract

Fallback must be explicit. Do not treat every provider error as permission to fall back.

Create provider-neutral outcome/failure classification sufficient to distinguish categories justified by runtime evidence, potentially transient/unavailable, rate limited, credential unavailable, authentication/authorization failure, model unavailable/not found, invalid request, context/input rejected, provider internal failure, and unknown/unclassified failure.

For every classification document whether fallback is allowed/denied, retry may be considered elsewhere, operator/runtime intervention is required, or classification remains adapter-owned.

The core must not import provider-specific exception classes.

---

# 11. Retry versus fallback ownership

Do not conflate retry with fallback.

Define the distinction based on runtime evidence. The routing core must not silently implement sleeping, backoff, or network retry loops.

Adapters/runtime may report provider-neutral failure evidence to routing orchestration.

---

# 12. Credential contract

Credentials remain adapter/runtime-owned. The core may carry only opaque credential references.

Inspect whether production supports multiple credentials per provider, rotation, credential pools, disabled/exhausted credentials, cooldown, and recovery.

Do not implement credential storage. Do not put API keys or tokens into fixtures, docs, or logs.

---

# 13. Credential failure safety

A credential failure must not expose or reuse secrets through core state.

Determine from runtime evidence whether credential failure permits another credential for the same provider/model, another model, another provider, or no fallback.

Do not invent the order. Document unknown mappings.

---

# 14. Candidate exhaustion

The core must explicitly represent the condition where no legal route remains.

Suggested provider-neutral statuses may include ROUTED, NO_ROUTE, EXHAUSTED, INVALID_REQUEST, FALLBACK_NOT_ALLOWED. Exact names may differ if justified.

Expose a stable reason code suitable for orchestration/audit. Do not use only a bare boolean.

---

# 15. Prompt-cache behavior

Inspect current production prompt-cache behavior and determine whether routing affects cache identity/affinity, provider/model affinity, session routing, fallback safety, or request reconstruction.

Do not implement a prompt cache in this sprint.

If evidence is insufficient, mark it UNVERIFIED. Fallback must not be declared cache-safe without evidence.

---

# 16. Session/profile routing scope

Inspect whether production routing decisions are scoped by global configuration, personality/profile, session, request, or route purpose.

Determine whether a session has a home provider/model or other affinity.

Do not add production session mutation to this sprint. Document cross-blocker dependencies where necessary.

---

# 17. Failure evidence

Create immutable provider-neutral failure evidence/value objects where useful.

Failure representation should carry stable failure classification/reason code, candidate identity, opaque credential reference if safe/required, and fallback policy evidence without provider exceptions, secrets, or raw credentials.

Provider adapters will eventually translate SDK/provider failures into this representation. Do not implement production adapters now.

---

# 18. Routing state machine / fallback progression

If progression through candidates is required, make it explicit and deterministic.

Required invariants:

- failed/exhausted candidate is not selected indefinitely;
- exhausted candidates are distinguishable from available candidates;
- fallback cannot jump to an unconfigured candidate;
- fallback ordering is deterministic;
- terminal no-route/exhausted state is explicit;
- failure evidence cannot mutate unrelated routing state.

Prefer immutable route-plan/progression objects where practical. Do not build an unnecessarily complex workflow engine.

---

# 19. Routing security invariants

Establish and test at least:

R1. Same deterministic inputs produce the same first route candidate.
R2. Route decision contains no secret credential material.
R3. Credential reference is opaque.
R4. Main/purpose routing remains distinguishable according to supported semantics.
R5. Higher-precedence legal candidate is selected first.
R6. Failed/exhausted candidate is not immediately reselected as fallback.
R7. Fallback selects only candidates already present in the legal route plan/configuration.
R8. Candidate ordering is deterministic.
R9. Fallback-permitted failure can advance to the next legal candidate.
R10. Fallback-denied failure does not advance.
R11. Exhausted candidate set produces explicit terminal result.
R12. Missing legal candidates fails closed with explicit result.
R13. Retry and fallback remain distinct concepts.
R14. Provider-specific exception objects do not enter core contracts.
R15. Credential secret material does not enter core contracts.
R16. Credential unavailability can be represented without secret leakage.
R17. Route/failure/result objects are immutable where required.
R18. Prompt-cache routing coupling is explicitly represented or documented UNVERIFIED.
R19. Existing routing C4 contract remains compatible or intentional changes are documented.
R20. Existing session, persistence, delivery and capability/approval contracts remain unaffected.

Add additional invariants if repository evidence reveals critical behavior.

---

# 20. Tests

Create deterministic isolated tests for R1-R20.

Tests must not use network, provider APIs, database, subprocess, sleeps, environment credentials, production credential stores, or production provider SDKs.

Use deterministic fake candidates/failure evidence. Test candidate order, fallback progression, terminal exhaustion, and absence of secret credential values.

Do not weaken existing routing tests merely to make the implementation pass.

---

# 21. Existing C4 compatibility

Review `tests/hermes_core/test_routing_contract.py`.

Preserve valid C4 behavior. Existing immutable `RouteDecision`, supported route purpose, and opaque credential reference contracts must remain green unless an intentional hardening change is necessary.

Document intentional semantic changes.

---

# 22. Architecture document

Create `docs/architecture/provider-routing-fallback-contract.md`.

Document purpose, baseline, production observations, routing boundary, route purpose/request/candidate/decision, deterministic precedence, fallback semantics, retry vs fallback, credential ownership/recovery, failure classification, candidate exhaustion, prompt-cache implications, session/profile scope, adapter responsibilities, known gaps, and migration implications.

Include a decision table using exact final implementation statuses.

---

# 23. Evidence document

Create `docs/architecture/provider-routing-fallback-hardening-evidence.md`.

Required sections:

1. Scope
2. Baseline
3. Runtime Observations
4. Existing C4 Contract
5. Route Purpose
6. Candidate Contract
7. Precedence Contract
8. Fallback Contract
9. Retry/Fallback Ownership
10. Credential Contract
11. Failure Classification
12. Prompt Cache
13. Session/Profile Scope
14. Test Evidence
15. Isolation Evidence
16. Compatibility Evidence
17. Known Gaps
18. Readiness Impact

Include one explicit evidence row for EACH R1-R20 with columns:

Contract | Test | Expected | Actual | Result | Evidence | Known limitation

For runtime observations include exact paths and VERIFIED/PARTIAL/UNVERIFIED.

---

# 24. Compatibility

Run the complete isolated `hermes_core` suite.

Prior session lifecycle, session persistence/CAS, delivery recovery, capability/approval enforcement, and existing routing C4 contracts must remain green.

Do not weaken previous security, concurrency, or recovery invariants.

---

# 25. Validation

Run:

    python -m pytest tests/hermes_core --confcutdir=tests/hermes_core -v
    python -m compileall hermes_core
    python -c "import hermes_core; print('hermes_core OK')"

Run the canonical repository runner:

    scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core

using the established isolated Python environment if required.

Also run:

    git diff --check
    git status --short
    git diff --stat
    git diff --name-only

Remember untracked files do not appear in ordinary `git diff`. Use `git add -N` for new files if necessary for final diff inspection.

---

# 26. Expected change scope

Likely files include existing routing domain/application/ports files, `tests/hermes_core/test_routing_contract.py`, a new `tests/hermes_core/test_provider_routing_fallback_contract.py`, and the two architecture/evidence documents.

Exact names may differ if justified.

Do not modify production runtime merely to satisfy isolated tests.

---

# 27. Readiness impact

At the end classify B5 as exactly one of:

- OPEN
- PARTIALLY_ADDRESSED
- READY_FOR_ADAPTER_VALIDATION

Do not mark B5 CLOSED solely because isolated core tests pass.

Production migration remains NO-GO unless the complete Migration Readiness Gate is separately reevaluated and explicitly changed.

---

# 28. Completion report

Report exact files changed; production runtime files inspected; runtime observations with VERIFIED/PARTIAL/UNVERIFIED; routing baseline; purpose/candidate/decision semantics; precedence/fallback algorithms; failure classifications; retry/fallback ownership; credential semantics/recovery; prompt-cache and session/profile findings; R1-R20 status; direct pytest; compile/import; canonical runner; isolation/compatibility; B5 status/gaps; production migration status; and git diff/status/stat/name-only outputs.

Do not commit.
Do not push.

Stop after implementation, validation, evidence generation and final report.
