# Sprint 1.5.4 — Capability & Approval Enforcement Contract Hardening

## Role

You are the Hermes Capability & Approval Enforcement Contract Architecture Agent.

Your task is to harden the isolated `hermes_core` tool-execution security contract so that future runtime adapters cannot execute protected or mutating tools merely because authorization metadata was propagated through the call stack.

This sprint addresses Migration Readiness Gate blocker B4.

The existing production Hermes runtime remains authoritative.

This sprint MUST NOT migrate production tool execution, approval handling, capability issuance, policy evaluation, or runtime ownership to `hermes_core`.

Do not commit.
Do not push.

---

# 1. Context

Sprint 1.5.1 established isolated core contract tests.
Sprint 1.5.2 hardened session/persistence contracts.
Sprint 1.5.3 hardened delivery/recovery contracts.

The current tool execution contract still has a critical security limitation.

`ToolExecutionContext` carries authorization-related information including `session_id`, `turn_id`, `tool_call_id`, `capability_grant`, and `approved`, but the application layer primarily propagates these values to the executor.

The current contract does not establish a fail-closed authorization boundary before protected tool execution.

The existing test `test_execution_context_preserves_unapproved_state_without_enforcing_it` explicitly demonstrates the current limitation.

This is insufficient for production migration.

---

# 2. Sprint objective

Create an explicit provider/runtime-neutral authorization contract for tool execution that answers:

1. Is this execution allowed?
2. Which principal/session/turn/tool call is authorized?
3. Which tool is authorized?
4. Which exact arguments are authorized?
5. Is human/user approval required?
6. If approval is required, was valid approval supplied?
7. Is the capability still valid?
8. Has it expired?
9. Has it been revoked?
10. Does the grant belong to this execution context?

The core must reject unauthorized execution BEFORE invoking `ToolExecutorPort`.

The security boundary must be deterministic and fail closed.

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

Do not import into `hermes_core` Telegram/Slack SDKs, HTTP clients, gateway runtime, database implementations, provider-specific auth objects, production approval managers, production capability stores, or production policy engines.

No network.
No database.
No subprocess.
No sleeps.
No wall-clock dependent tests.
No credentials.

Use immutable provider-neutral value objects.

---

# 4. Capability grant contract

Replace the current opaque/optional capability representation where necessary with an explicit immutable capability grant/value object.

The contract must be capable of binding authorization to at least:

- grant_id
- principal_id
- session_id
- turn_id
- tool_call_id
- tool_name
- canonical/final arguments or their deterministic digest
- approval requirement
- issued validity information
- expiry information
- revocation state or revocation evidence
- policy/version reference

Do not store secrets or provider SDK objects.
Do not require production persistence implementation in this sprint.
If some fields must remain adapter-owned, document that explicitly.

---

# 5. Argument binding

Authorization MUST apply to the exact arguments that will be executed.

A grant for:

    tool = "send_message"
    args = {"recipient": "A", "text": "hello"}

must not authorize:

    {"recipient": "B", "text": "hello"}

or any other mutation of the final arguments.

Define a deterministic argument-binding mechanism.

Preferred direction: canonical representation + deterministic digest.

The core contract must not depend on dictionary insertion order. Equivalent argument objects must produce the same binding. Different security-relevant arguments must produce different bindings.

Do not introduce cryptographic key management.

A deterministic digest such as SHA-256 over canonical serialized arguments is acceptable as a contract mechanism.

---

# 6. Approval semantics

Do not model approval as an unrestricted boolean that automatically authorizes execution.

The contract must distinguish at least:

- approval not required;
- approval required but absent;
- approval required and valid;
- approval supplied for a different execution;
- approval invalid/stale/revoked where representable.

Approval must be bound to the execution identity.

At minimum bind approval to:

- session
- turn
- tool_call
- tool
- final argument binding

If the existing runtime does not expose all these semantics, document the gap.
Do not invent production behavior.

---

# 7. Capability validation result

Create an explicit immutable validation/authorization result.

Suggested statuses may include:

- AUTHORIZED
- DENIED
- APPROVAL_REQUIRED
- EXPIRED
- REVOKED
- CONTEXT_MISMATCH
- ARGUMENT_MISMATCH
- INVALID_GRANT

Exact names may differ if justified.

Do not use a bare bool as the complete authorization result.

The result should expose stable provider-neutral reason/error codes suitable for application orchestration and audit.

Do not leak secrets.

---

# 8. Enforcement boundary

The application layer must enforce authorization BEFORE `ToolExecutorPort.execute(...)`.

Required invariant:

    if authorization != AUTHORIZED:
        executor MUST NOT be called

This must be directly tested by executor call count.

No fail-open behavior is allowed.

Missing grant for a protected execution must not silently execute.
Missing required approval must not silently execute.
Expired/revoked/mismatched grant must not execute.
Argument mismatch must not execute.

---

# 9. Protected vs unprotected execution

Inspect the existing runtime and architecture documents before choosing semantics.

Determine whether Hermes currently distinguishes:

- read-only tools
- mutating tools
- tools requiring explicit approval
- tools permitted by capability/policy without approval

Do not invent categories unsupported by repository evidence.

If the production distinction cannot be established, design the isolated contract conservatively and mark runtime mapping UNVERIFIED.

The core must not assume every tool requires identical approval behavior.

---

# 10. Time / expiry semantics

Expiry must be deterministic in tests.

Do not call wall-clock time directly from domain objects.

Use one of:

- explicit evaluation time passed to validation;
- immutable timestamp supplied by caller;
- provider-neutral ClockPort if truly necessary.

Prefer the simplest deterministic design.

Tests must not sleep.

---

# 11. Revocation semantics

A capability that is known to be revoked must not authorize execution.

Do not implement a production revocation database.

Represent revocation in a provider-neutral way that future adapters can supply to the core validation boundary.

Document which component will eventually own durable revocation state.

---

# 12. Security invariants

The resulting contract must establish:

S1. Unauthorized execution never reaches executor.
S2. Required approval absent -> executor not called.
S3. Valid authorization -> executor called exactly once.
S4. Grant bound to another session -> denied.
S5. Grant bound to another turn -> denied.
S6. Grant bound to another tool_call -> denied.
S7. Grant bound to another tool -> denied.
S8. Grant bound to different final arguments -> denied.
S9. Equivalent canonical arguments -> same binding.
S10. Argument ordering does not affect binding.
S11. Expired grant -> denied.
S12. Revoked grant -> denied.
S13. Approval for different execution -> denied.
S14. Approval-required execution with valid bound approval -> authorized.
S15. Approval-not-required grant does not require fake approval.
S16. Missing/malformed grant fails closed where authorization is required.
S17. Authorization result exposes stable provider-neutral denial reason.
S18. Executor cannot decide to bypass application authorization.
S19. Provider/runtime-specific auth objects do not enter core contracts.
S20. Existing session/delivery/routing contracts remain unaffected.

---

# 13. Tests

Create deterministic isolated tests for S1-S20.

Tests must not use network, real provider APIs, database, subprocess, sleeps, environment credentials, or production approval services.

Use deterministic fake policy/authorization components where necessary.

Executor call count must be asserted for deny-before-execute scenarios.

Do not weaken existing tests merely to make the new implementation pass.

The existing test `test_execution_context_preserves_unapproved_state_without_enforcing_it` must either be replaced by the new enforcement expectation or intentionally rewritten with evidence explaining the contract change.

It must not remain as evidence that unapproved execution is acceptable.

---

# 14. Runtime inspection

Before finalizing the contract, inspect the authoritative production runtime for current behavior related to:

- tool execution entry point;
- approval checks;
- capability/policy checks;
- mutating vs read-only classification;
- principal/user identity;
- session binding;
- turn/tool-call identity;
- argument mutation after approval;
- approval lifetime;
- revocation;
- policy versioning;
- audit logging.

Record actual file/path evidence.

For every property use one of:

- VERIFIED
- PARTIAL
- UNVERIFIED

Do not infer unsupported production behavior.
Do not modify those runtime paths.

---

# 15. Architecture document

Create `docs/architecture/capability-approval-enforcement.md`.

Document:

1. purpose;
2. threat model;
3. authorization boundary;
4. capability grant structure;
5. execution identity;
6. argument canonicalization/binding;
7. approval binding;
8. expiry;
9. revocation;
10. authorization statuses;
11. deny-before-execute invariant;
12. protected/unprotected tool semantics;
13. adapter responsibilities;
14. runtime mapping;
15. known gaps;
16. migration implications.

Include a decision table similar to:

| Condition | Authorization result | Executor called? |
|---|---|---|
| valid grant, no approval required | AUTHORIZED | yes |
| valid grant, approval required, valid approval | AUTHORIZED | yes |
| approval required, absent | APPROVAL_REQUIRED | no |
| wrong session | CONTEXT_MISMATCH | no |
| wrong tool | CONTEXT_MISMATCH | no |
| args changed after authorization | ARGUMENT_MISMATCH | no |
| expired | EXPIRED | no |
| revoked | REVOKED | no |
| malformed/missing required grant | DENIED/INVALID_GRANT | no |

Use exact final implementation status names.

---

# 16. Evidence document

Create `docs/architecture/capability-approval-hardening-evidence.md`.

Required sections:

1. Scope
2. Baseline
3. Runtime Observations
4. Threat Model
5. Capability Grant Contract
6. Argument Binding Contract
7. Approval Contract
8. Expiry Contract
9. Revocation Contract
10. Authorization Result Contract
11. Enforcement Boundary
12. Test Evidence
13. Isolation Evidence
14. Compatibility Evidence
15. Known Gaps
16. Readiness Impact

Include one explicit evidence row for EACH S1-S20.

Columns:

Contract | Test | Expected | Actual | Result | Evidence | Known limitation

Do not collapse S1-S20 into a single row.

---

# 17. Compatibility

Run the complete isolated `hermes_core` suite.

The following prior contracts must remain green:

- session lifecycle;
- session persistence/CAS;
- delivery recovery;
- routing;
- existing tool argument/context behavior that remains valid.

Any intentional change to the old tool approval behavior must be explicitly documented.

Do not weaken previous security or recovery invariants.

---

# 18. Validation

Run:

    python -m pytest tests/hermes_core --confcutdir=tests/hermes_core -v
    python -m compileall hermes_core
    python -c "import hermes_core; print('hermes_core OK')"

Run the canonical repository runner:

    scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core

using the repository's established isolated Python environment if required.

Also run:

    git diff --check
    git status --short
    git diff --stat
    git diff --name-only

---

# 19. Expected change scope

Likely files include:

    hermes_core/domain/<capability-or-authorization>.py
    hermes_core/application/execution_service.py
    hermes_core/ports/tools.py

    tests/hermes_core/test_tool_execution_contract.py
    tests/hermes_core/test_capability_approval_contract.py

    docs/architecture/capability-approval-enforcement.md
    docs/architecture/capability-approval-hardening-evidence.md

Exact names may differ if justified.

Do not modify production runtime merely to satisfy isolated tests.

---

# 20. Readiness impact

At the end classify B4 as exactly one of:

- OPEN
- PARTIALLY_ADDRESSED
- READY_FOR_ADAPTER_VALIDATION

Do not mark B4 CLOSED solely because isolated core tests pass.

Production migration remains NO-GO unless the complete Migration Readiness Gate is separately reevaluated and explicitly changed.

This sprint alone cannot authorize production migration.

---

# 21. Completion report

Report:

- exact files changed;
- runtime files inspected;
- runtime observations and VERIFIED/PARTIAL/UNVERIFIED status;
- capability grant fields;
- argument-binding algorithm;
- approval-binding semantics;
- expiry semantics;
- revocation semantics;
- authorization statuses;
- deny-before-execute behavior;
- S1-S20 status;
- direct pytest result;
- compile/import result;
- canonical runner result;
- isolation result;
- compatibility result;
- B4 readiness status;
- remaining B4 gaps;
- production migration status;
- git diff --check;
- git diff --stat;
- git diff --name-only.

Do not commit.
Do not push.

Stop after implementation, validation, evidence generation, and final report.
