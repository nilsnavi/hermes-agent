# Intent Router Evaluation — Sprint 1.1.0

## Evaluation result

Evaluation date: 2026-08-12. Dataset is synthetic and contains no production prompts.

| Metric | Result | Gate | Status |
|---|---:|---:|---|
| Total cases | 382 | — | — |
| Russian cases | 210 (55.0%) | >= 40% | PASS |
| English cases | 172 (45.0%) | > 0 | PASS |
| Adversarial/edge cases | 49 | >= 10 | PASS |
| Ambiguous cases | 24 by case-id group; 27 expected UNKNOWN after relabel | — | — |
| Intent accuracy | 1.0000 | >= 0.98 | PASS |
| RU accuracy | 1.0000 (210/210) | — | PASS |
| EN accuracy | 1.0000 (172/172) | — | PASS |
| Class accuracy | 1.0000 | — | PASS |
| Read-only precision | 1.0000 | = 1.0 | PASS |
| Unsafe predicted READ_ONLY | 0 | = 0 | PASS |
| Unsafe predicted canary | 0 | = 0 | PASS |
| Unknown rate | 0.0707 | — | — |
| Legacy recommendation rate | 0.8822 | — | — |

The three objectless phrases `ru_adv_3`, `en_adv_3`, and `en2_adv_9` are labeled `UNKNOWN`; classifier rules were not strengthened around objectless “fix/исправь” wording. `en2_schedule_4` uses the unambiguous synthetic schedule text `run hourly cron checks`.

## Safety confusion matrix

Rows are true labeled classes; columns are predicted classes. Zero cells are shown explicitly because they are safety gates.

| True class | Predicted READ_ONLY | Predicted WRITE | Predicted SYSTEM | Predicted SCHEDULE | Predicted UNKNOWN | Effective V2_CANARY |
|---|---:|---:|---:|---:|---:|---:|
| READ_ONLY | 118 | 0 | 0 | 0 | 0 | not a leakage gate |
| WRITE (includes delete intents in evaluation class) | 0 | 106 | 0 | 0 | 0 | **0** |
| SYSTEM | 0 | 0 | 38 | 0 | 0 | **0** |
| SCHEDULE | 0 | 0 | 0 | 20 | 0 | 0 |
| UNKNOWN | 0 | 0 | 0 | 0 | 27 | **0** |

Additional correctly classified diagonal cells:

| True -> predicted | Count |
|---|---:|
| analysis -> analysis | 22 |
| approval -> approval | 13 |
| code -> code | 12 |
| conversation -> conversation | 17 |
| planning -> planning | 9 |

Mandatory route-leakage counters:

| Counter | Result |
|---|---:|
| WRITE -> effective V2_CANARY | 0 |
| DELETE -> effective V2_CANARY | 0 |
| SYSTEM -> effective V2_CANARY | 0 |
| UNKNOWN -> effective V2_CANARY | 0 |
| Unsafe predicted READ_ONLY | 0 |

All dangerous cells are zero.

## Performance

Measured over 10,000 complete `features_from_text + IntentRouter.observe` classify-and-route decisions after one warm-up call:

| Metric | Result |
|---|---:|
| Total | 14,229.294 ms (14.229 s) |
| Average | 1.421538 ms/decision |
| p50 | 1.445653 ms |
| p95 | 1.610298 ms |
| Router errors | 0 |

The benchmark uses the deterministic local Python router with a stubbed healthy runtime snapshot. It performs no network calls, LLM calls, or database operations. Low-millisecond latency satisfies the Sprint 1.1.0 objective; dependency isolation is the primary performance/safety property.

## Tests

| Scope | Result |
|---|---:|
| Targeted RED before fix | 4 expected failures |
| Targeted GREEN after fix | 34 passed, 0 failed |
| `scripts/run_tests.sh tests/intent_router` | 129 passed, 0 failed |
| Canonical Sprint 1.1.0 scope | 648 passed, 0 failed |
| compileall for canonical packages | PASS |
| New V2 regressions | 0 |

Canonical scope:

```text
tests/runtime
tests/execution
tests/persistence
tests/recovery
tests/orchestrator
tests/gateway_v2
tests/operations_v2
tests/intent_router
```

No unrelated pre-existing/environment failures occurred in this scope; none were modified.

## Quality gate

- [x] Intent accuracy >= 98%
- [x] Read-only precision = 1.0
- [x] Unsafe predicted READ_ONLY = 0
- [x] WRITE -> effective V2_CANARY = 0
- [x] DELETE -> effective V2_CANARY = 0
- [x] SYSTEM -> effective V2_CANARY = 0
- [x] UNKNOWN -> effective V2_CANARY = 0
- [x] IntentRouter tool calls = 0
- [x] Production routing changes = 0

## Sprint 1.1.1 calibration rule

Do not change classifier rules in Sprint 1.1.1 unless live observe produces evidence of a systematic, reproducible misclassification. The Sprint 1.1.0 classifier must remain stable while its quality is measured on the production observe sample.

## Sprint 1.1.1 — re-evaluation after gateway hook integration

Re-run of the full 382-case dataset after the observe hook was wired into
the production gateway (`gateway/run.py` → `agent/intent_router/gateway_hook.py`).
Purpose: prove the hook/context changes did not alter classifier behavior
(§20). Dataset: 2026-08-13.

| Metric | Result | Gate | Status |
|---|---:|---:|---|
| Total cases | 382/382 | — | PASS |
| Intent accuracy | 1.0000 | >= 0.98 | PASS |
| RU accuracy | 1.0000 (210/210) | — | PASS |
| EN accuracy | 1.0000 (172/172) | — | PASS |
| Read-only precision | 1.0000 | = 1.0 | PASS |
| Unsafe predicted READ_ONLY | 0 | = 0 | PASS |
| WRITE → V2_CANARY | 0 | = 0 | PASS |
| DELETE → V2_CANARY | 0 | = 0 | PASS |
| SYSTEM → V2_CANARY | 0 | = 0 | PASS |
| UNKNOWN → V2_CANARY | 0 | = 0 | PASS |
| Unknown rate | 0.0707 | — | — |
| Legacy recommendation rate | 0.8822 | — | — |

Classifier rules: **unchanged** (rule freeze §24). No calibration findings
require a rule change.

## Sprint 1.1.1 — observe calibration tests

New file `tests/intent_router/test_observe_calibration.py` (§40):
`test_router_disabled_not_called`, `test_observe_actual_route_unchanged`,
`test_observe_response_unchanged`, `test_observe_tool_calls_unchanged`,
`test_router_exception_isolated`, `test_telemetry_no_prompt`,
`test_telemetry_no_secret`, `test_event_payload_whitelist`,
`test_actual_route_enum`, `test_sample_source`, `test_policy_vs_classifier_mismatch`
(via metrics), `test_router_metrics`, `test_router_health`,
`test_config_writer_preserves_sections_on_flag_update`, mode-guard tests
(ENFORCE/SHADOW_DECISION → OFF).
