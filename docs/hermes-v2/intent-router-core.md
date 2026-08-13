# Intent Router Core — Sprint 1.1.0

## Status

The Intent Router is a deterministic, rule-based **observe/recommend-only** component. It classifies a normalized request, evaluates risk and capability eligibility, and produces candidate/effective routing recommendations. It is not an execution authority.

Production authority remains the existing gateway policy. Ordinary traffic is not switched by the router.

## Processing contract

```text
RequestIntentFeatures
  -> RuleBasedIntentClassifier
  -> CapabilityRegistry
  -> RouterPolicy
  -> IntentRoutingDecision
  -> whitelisted in-memory observation event
```

`RequestIntentFeatures` contains safe normalized metadata and lexical family names, not raw prompt text. `IntentRoutingDecision` separates:

- intent;
- risk;
- expected side effect;
- candidate route;
- effective route;
- confidence and structured reason codes;
- required capabilities and eligible tools.

## Taxonomy

Intent types:

- conversation, summarization;
- information/status/search read;
- analysis, planning, code assist, diagnostic;
- approval, write, delete, system, schedule;
- unknown.

Risk and intent are independent. Side-effect expectation is also independent from actual tool metadata.

## Safety policy

- `UNKNOWN` fails closed to effective `LEGACY`.
- Write, delete, system, schedule, and approval intents never receive effective `V2_CANARY`.
- Delete is deny-oriented; other unsafe actions may be recommended for approval, but approval does not authorize execution.
- Canary eligibility requires read-only/none side effect, supported capability, allowed risk, sufficient confidence, explicit internal allowlist, enabled canary flag, and healthy runtime.
- Unknown/unhealthy state fails closed.
- Router exceptions return a `LEGACY` decision with `router_error`.

Only `READ_RUNTIME_STATUS` is currently declared as a verified V2 capability. No write/delete/system capability is advertised.

## Modes and flags

Code defaults:

```text
HERMES_INTENT_ROUTER_ENABLED=false
HERMES_INTENT_ROUTER_MODE=off
```

Sprint 1.1.0 supports OFF and OBSERVE semantics. ENFORCE parses fail-closed to OFF. This continuation did not change systemd units, environment flags, or production activation.

A pre-existing observe-only gateway hook calls `IntentRouter.observe(...)` only when explicitly enabled in observe mode. It logs the recommendation and preserves existing routing on success or error. No gateway hook was changed during this continuation.

## Data and dependency boundaries

The router package:

- does not call `ToolRuntime.execute`;
- does not call `RuntimeOrchestrator.run` or `.resume`;
- does not write production/state databases;
- does not persist raw prompts, authorization, tool arguments, or full metadata;
- does not depend on a network service or LLM;
- emits only whitelisted fields to a bounded in-memory event ring by default.

The default health provider is cached for 30 seconds. Any health-probe failure becomes `unknown` and blocks effective canary routing.

## Architectural verification — 2026-08-12

| Check | Result |
|---|---:|
| `ToolRuntime.execute` calls from `agent/intent_router` | 0 |
| `RuntimeOrchestrator.run/resume` calls | 0 |
| Production DB writes | 0 |
| Gateway hook changes in this continuation | 0 |
| systemd/flag changes in this continuation | 0 |
| Actual production routes changed | 0 |

Static source search found no execution/runtime/database call sites in `agent/intent_router`. Canonical tests also verify observe-mode non-mutation, no thread creation, event field whitelisting, fail-closed behavior, health/allowlist gates, and unsafe-route guards.

## Verification commands

```bash
venv/bin/python -m compileall -q \
  agent/runtime agent/execution agent/persistence agent/recovery \
  agent/orchestrator agent/gateway_v2 agent/operations_v2 \
  agent/intent_router

scripts/run_tests.sh tests/intent_router

scripts/run_tests.sh \
  tests/runtime tests/execution tests/persistence tests/recovery \
  tests/orchestrator tests/gateway_v2 tests/operations_v2 \
  tests/intent_router
```

Measured results:

- compileall: PASS;
- Intent Router: 129 passed, 0 failed;
- canonical Sprint 1.1.0 scope: 648 passed, 0 failed.

## Sprint 1.1.1 calibration freeze

Sprint 1.1.1 must not change classifier rules unless production observe data demonstrates a systematic misclassification with reproducible evidence. This preserves the integrity of measuring the Sprint 1.1.0 classifier against a production sample.
