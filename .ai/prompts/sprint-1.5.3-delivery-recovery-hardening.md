# Hermes 2.0 — Sprint 1.5.3 Delivery Recovery Contract Hardening

## Role

You are the Hermes Delivery Recovery Contract Architecture Agent.

Your task is to harden the isolated `hermes_core` delivery contracts so that future
delivery adapters can safely represent confirmed success, confirmed failure,
ambiguous transport acknowledgement, recovery, and terminal abandonment without
causing duplicate external side effects.

This sprint addresses Migration Readiness Gate blocker **B3**.

The existing production runtime remains authoritative.

This sprint MUST NOT migrate production delivery ownership.

---

# 1. Mission

Strengthen the delivery domain/application/port contracts so that Hermes can
distinguish:

- delivery not attempted,
- delivery currently attempting,
- confirmed external success,
- confirmed external failure,
- unknown external acknowledgement,
- terminal abandonment.

The core contract must preserve enough transport evidence for future recovery
without embedding Telegram, Slack, HTTP, SDK, database, queue, or provider-specific
implementation details.

The primary safety property is:

> An ambiguous transport outcome must never be silently treated as a confirmed
> failure that is automatically safe to retry.

---

# 2. Non-goals

Do NOT:

- connect `hermes_core` to the production delivery runtime;
- replace existing gateway delivery code;
- change production Telegram/Slack/provider behavior;
- send real messages;
- introduce production queues;
- introduce production retry workers;
- implement migration flags;
- transfer delivery ownership;
- change production database schemas;
- remove legacy delivery paths;
- implement provider-specific reconciliation;
- declare production migration GO;
- commit;
- push.

Production migration remains **NO-GO**.

---

# 3. Mandatory inspection

Before implementation inspect at minimum:

- `hermes_core/domain/delivery.py`
- `hermes_core/application/delivery_service.py`
- `hermes_core/ports/delivery.py`
- existing delivery contract tests
- Sprint 1.5.0 migration readiness gate
- Sprint 1.5.1 contract evidence
- Sprint 1.5.2 evidence where relevant

Also inspect the authoritative runtime delivery/send/retry/recovery paths.

Identify:

- where external sends occur;
- what constitutes confirmed success;
- what constitutes confirmed failure;
- what happens on timeout;
- what happens when the connection drops after send;
- whether external message IDs are persisted;
- whether retryability is currently preserved;
- where retry decisions are made;
- whether duplicate-send protection exists;
- what recovery/reconciliation mechanisms exist;
- what happens after process crash between external send and local persistence.

Document observed runtime behavior.

Do not modify production runtime code.

---

# 4. Delivery state model

The core delivery state model must explicitly support at least:

- `PENDING`
- `ATTEMPTING`
- `DELIVERED`
- `FAILED`
- `UNKNOWN_ACK`
- `ABANDONED`

Names may differ only if the semantics remain explicit and documented.

## UNKNOWN_ACK

`UNKNOWN_ACK` means:

> The external side effect may have occurred, but Hermes does not have enough
> evidence to classify the attempt as confirmed success or confirmed failure.

Examples:

- request timeout after payload transmission;
- connection loss after remote acceptance may have occurred;
- process crash after external send but before durable confirmation;
- adapter reports ambiguous acknowledgement.

`UNKNOWN_ACK` MUST NOT be treated as ordinary `FAILED`.

It MUST NOT imply that retry is safe.

## ABANDONED

`ABANDONED` means:

> Hermes intentionally stops automatic recovery/retry for this delivery attempt
> because a safe outcome cannot be established or policy explicitly terminates
> recovery.

ABANDONED is terminal unless a future explicitly authorized manual/recovery
operation defines otherwise.

---

# 5. Transport result contract

Review and harden `DeliveryResult`.

The application layer must not lose transport evidence.

Preserve at minimum where applicable:

- success/failure/unknown outcome;
- `external_id`;
- `retryable`;
- error classification;
- stable error code or reason;
- acknowledgement certainty.

Do not put SDK exceptions or provider objects into domain/application contracts.

Prefer immutable value objects.

The transport result must allow application logic to distinguish:

1. confirmed success;
2. confirmed failure;
3. ambiguous acknowledgement.

A boolean `success` alone is insufficient if ambiguity cannot be represented.

---

# 6. Application result contract

`DeliveryService` must return enough information for orchestration and recovery.

Do not return only a delivery state if doing so discards:

- external ID;
- retryability;
- error classification;
- acknowledgement certainty.

Define an explicit immutable application result if needed.

The result should make the following outcomes distinguishable:

- SUCCESS
- FAILURE
- UNKNOWN_ACK
- REJECTED / INVALID_TRANSITION
- TRANSPORT_ERROR where appropriate

Do not conflate transport failure with unknown acknowledgement.

---

# 7. Retry ownership

Retry policy MUST remain outside the transport adapter.

The transport adapter may report:

- retryable hint;
- error class;
- acknowledgement certainty.

It MUST NOT autonomously retry unless the existing architecture explicitly assigns
that ownership and the contract documents it.

The application/domain contract MUST NOT automatically retry `UNKNOWN_ACK`.

Document exactly which layer owns future retry decisions.

---

# 8. Duplicate side-effect safety

Define the safety rule:

> No retry may be considered safe solely because the previous attempt lacks a
> confirmed local success record.

A missing local ACK is not proof that the external side effect did not occur.

Document how future adapters may use mechanisms such as:

- external idempotency keys;
- provider message IDs;
- reconciliation APIs;
- durable attempt IDs;
- deduplication records;

without requiring those mechanisms in this isolated sprint.

Provider-specific implementation remains adapter-owned.

---

# 9. Recovery semantics

Define legal recovery transitions.

At minimum reason about:

PENDING -> ATTEMPTING

ATTEMPTING -> DELIVERED
ATTEMPTING -> FAILED
ATTEMPTING -> UNKNOWN_ACK

UNKNOWN_ACK -> DELIVERED
UNKNOWN_ACK -> FAILED
UNKNOWN_ACK -> ABANDONED

Do not permit arbitrary terminal-state rewrites.

If FAILED can later be retried, retry must create or begin an explicitly modelled
new attempt rather than silently rewriting history.

Document whether attempt count / attempt identity belongs in core now or remains
future adapter/application metadata.

Do not over-model it unless required for correctness.

---

# 10. Exception semantics

Do not assume every transport exception means confirmed failure.

Review the current `DeliveryService` behavior where transport exceptions currently
mark delivery failed and are re-raised.

Harden the contract so ambiguous exceptions can become `UNKNOWN_ACK`.

If the port cannot currently classify exception certainty, introduce a narrow
provider-neutral result/error contract.

Do not expose provider SDK exception types through the port.

---

# 11. Required contract tests

Create isolated deterministic tests.

At minimum:

D1. delivery starts PENDING.

D2. begin attempt enters ATTEMPTING.

D3. confirmed success enters DELIVERED.

D4. confirmed failure enters FAILED.

D5. ambiguous acknowledgement enters UNKNOWN_ACK.

D6. UNKNOWN_ACK is not treated as FAILED.

D7. UNKNOWN_ACK does not automatically retry.

D8. transport evidence preserves external_id.

D9. transport evidence preserves retryable hint.

D10. transport evidence preserves error/reason classification.

D11. UNKNOWN_ACK can reconcile to DELIVERED.

D12. UNKNOWN_ACK can reconcile to FAILED.

D13. UNKNOWN_ACK can terminate as ABANDONED.

D14. ABANDONED is terminal.

D15. DELIVERED cannot be rewritten to FAILED by a stale/late result.

D16. confirmed failure and ambiguous acknowledgement remain distinguishable at
the application result boundary.

D17. transport/provider-specific exception objects do not leak into the core
contract.

D18. existing Sprint 1.5.1 delivery contract expectations remain valid unless an
intentional contract change is explicitly documented.

Tests MUST NOT use:

- network;
- real Telegram/Slack/provider APIs;
- database;
- subprocess;
- sleeps;
- timing races;
- credentials.

Use deterministic fakes.

---

# 12. Crash-window analysis

Create:

`docs/architecture/delivery-recovery-contract.md`

Include a crash-window matrix with at least:

| Crash / failure point | External side effect possible? | Local evidence | Safe classification | Automatic retry safe? | Required future mechanism |

Analyze at minimum:

1. before send;
2. during request before payload transmission;
3. after payload transmission but before response;
4. after remote success but before local persistence;
5. after local persistence;
6. process crash while ATTEMPTING;
7. recovery of UNKNOWN_ACK.

Do not claim automatic retry is safe where external success is uncertain.

---

# 13. Evidence document

Create:

`docs/architecture/delivery-recovery-hardening-evidence.md`

Required sections:

1. Scope
2. Baseline
3. Runtime Observations
4. Delivery State Contract
5. Transport Result Contract
6. Application Result Contract
7. Retry Ownership
8. Duplicate-Side-Effect Safety
9. Recovery Semantics
10. Crash-Window Analysis
11. Test Evidence
12. Isolation Evidence
13. Known Gaps
14. Readiness Impact

For D1-D18 record:

- Contract
- Test
- Expected
- Actual
- Result
- Evidence
- Known limitation

Do not claim evidence that was not actually executed.

---

# 14. Compatibility

Run the complete isolated Hermes core contract suite.

Sprint 1.5.3 MUST NOT weaken:

- session contracts;
- persistence/CAS contracts;
- routing contracts;
- tool execution contracts.

If an existing delivery test changes because the old behavior was unsafe, document
the intentional semantic change explicitly.

In particular, if:

transport exception -> FAILED

changes to a classified:

confirmed failure -> FAILED
ambiguous outcome -> UNKNOWN_ACK

document this as an intentional hardening.

---

# 15. Validation

Run:

python -m pytest tests/hermes_core --confcutdir=tests/hermes_core -v

python -m compileall hermes_core

python -c "import hermes_core; print('hermes_core OK')"

Also run the canonical repository test runner:

& 'C:\Program Files\Git\bin\bash.exe' -lc 'export PATH=/usr/bin:/bin:$PATH; export HERMES_PYTHON=/c/Users/Navitech-home/AppData/Local/Temp/hermes-core-contract-151/Scripts/python.exe; scripts/run_tests.sh tests/hermes_core --confcutdir=tests/hermes_core'

If that isolated environment no longer exists, use a valid isolated environment and
record exactly what was used.

Also run:

git diff --check
git status --short
git diff --stat
git diff --name-only

Do not run or claim the full production regression suite unless it was actually run.

---

# 16. Architecture boundary

Maintain:

domain
  ↑
application
  ↑
ports
  ↑
future adapters

Core must not import:

- Telegram SDKs;
- Slack SDKs;
- HTTP clients;
- gateway runtime;
- database implementations;
- queue implementations;
- provider-specific exceptions.

Transport-specific behavior belongs behind ports/adapters.

---

# 17. Readiness impact

At the end classify B3 only as one of:

- OPEN
- PARTIALLY_ADDRESSED
- READY_FOR_ADAPTER_VALIDATION

Do NOT mark B3 CLOSED solely from isolated core tests.

Production migration remains NO-GO.

Do not change B1/B2 status merely because Sprint 1.5.3 passes.

---

# 18. Expected change areas

Expected:

- `hermes_core/domain/delivery.py`
- `hermes_core/application/delivery_service.py`
- `hermes_core/ports/delivery.py`
- delivery contract tests
- new delivery recovery tests if useful
- `docs/architecture/delivery-recovery-contract.md`
- `docs/architecture/delivery-recovery-hardening-evidence.md`

Unexpected and prohibited without explicit justification:

- production gateway send implementation;
- production provider adapters;
- SessionDB;
- migration controller;
- production schemas;
- unrelated capability/routing/session code.

---

# 19. Final report

At completion report:

1. exact files changed;
2. delivery states added/changed;
3. transport result changes;
4. application result changes;
5. retry ownership;
6. UNKNOWN_ACK semantics;
7. ABANDONED semantics;
8. crash-window findings;
9. D1-D18 results;
10. complete isolated test result;
11. canonical runner result;
12. B3 status;
13. remaining blockers;
14. `git diff --stat`;
15. `git diff --name-only`.

Do NOT commit.
Do NOT push.

Stop after Sprint 1.5.3 implementation and evidence generation.
