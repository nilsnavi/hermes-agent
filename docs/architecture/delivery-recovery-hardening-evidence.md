# Sprint 1.5.3 delivery recovery hardening evidence

## 1. Scope
Изолированный `hermes_core`; production delivery ownership и runtime paths не изменялись.

## 2. Baseline
До спринта core имел только четыре состояния, boolean success и перевод всех исключений в FAILED.

## 3. Runtime Observations
Проверены `gateway/`, `gateway/platforms/`, `gateway/session_transcript.py`, `hermes_state_messages.py` и существующие delivery tests. Внешняя отправка принадлежит platform adapters; core не вызывается runtime. Подтверждённый успех определяется adapter result/внешним message id, подтверждённая ошибка — definitive transport result. Поведение timeout/connection loss, duplicate-send protection, reconciliation и crash после remote side effect до durable ACK в runtime не установлено (`UNVERIFIED`); external IDs и retry hints в текущем core C2 передаются как transport data. Retry ownership и recovery ledger production path не передаются core.

## 4. Delivery State Contract
Добавлены UNKNOWN_ACK и ABANDONED; UNKNOWN_ACK не является FAILED и не запускает автоматический retry.

## 5. Transport Result Contract
`DeliveryResult` сохраняет outcome, external_id, retryable, error и error_code. Provider-neutral `DeliveryTransportError` не раскрывает SDK object.

## 6. Application Result Contract
`DeliveryApplicationResult` различает SUCCESS, FAILURE, UNKNOWN_ACK, REJECTED, TRANSPORT_ERROR и ABANDONED и переносит transport evidence.

## 7. Retry Ownership
Retry policy остаётся у application/orchestration; adapter только сообщает hint и certainty.

## 8. Duplicate-Side-Effect Safety
Отсутствие local ACK не доказывает отсутствие внешнего side effect; retry UNKNOWN_ACK запрещён до reconciliation/idempotency evidence.

## 9. Recovery Semantics
Разрешены только переходы, перечисленные в `delivery-recovery-contract.md`; ABANDONED terminal.

## 10. Crash-Window Analysis
Матрица crash windows находится в `docs/architecture/delivery-recovery-contract.md`.

## 11. Test Evidence

| Contract | Test | Expected | Actual | Result | Evidence | Known limitation |
|---|---|---|---|---|---|---|
| D1 | `test_d1_pending` | PENDING | passed | PASS | isolated fake | no adapter |
| D2 | `test_d2_attempting` | ATTEMPTING | passed | PASS | isolated fake | no adapter |
| D3 | `test_d3_confirmed_success` | DELIVERED | passed | PASS | isolated fake | no adapter |
| D4 | `test_d4_confirmed_failure` | FAILED | passed | PASS | isolated fake | no adapter |
| D5 | `test_d5_ambiguous_ack` | UNKNOWN_ACK | passed | PASS | isolated fake | no adapter |
| D6 | `test_d6_unknown_is_not_failed` | distinct state | passed | PASS | isolated fake | — |
| D7 | `test_d7_unknown_does_not_retry` | no retry | passed | PASS | call count | no scheduler |
| D8 | `test_d8_external_id_preserved` | ID retained | passed | PASS | result assertion | — |
| D9 | `test_d9_retryable_preserved` | hint retained | passed | PASS | result assertion | policy external |
| D10 | `test_d10_error_classification_preserved` | code/reason retained | passed | PASS | result assertion | — |
| D11 | `test_d11_unknown_reconcile_delivered` | reconcile success | passed | PASS | state/result | no provider |
| D12 | `test_d12_unknown_reconcile_failed` | reconcile failure | passed | PASS | state/result | no provider |
| D13 | `test_d13_unknown_abandon` | ABANDONED + status | passed | PASS | state/result | — |
| D14 | `test_d14_abandoned_terminal` | all rewrites rejected | passed | PASS | state/result | — |
| D15 | `test_d15_delivered_cannot_be_rewritten` | late failure rejected | passed | PASS | domain guard | no concurrency |
| D16 | `test_d16_application_distinguishes_failure_and_unknown` | distinct statuses | passed | PASS | result assertions | — |
| D17 | `test_d17_provider_exception_does_not_enter_contract` | neutral boundary | passed | PASS | no SDK object in result | provider fake only |
| D18 | `test_d18_existing_contract_remains_valid` + C2 | compatibility | passed | PASS | 57-test suite run | exception hardening documented |

Additional corrective test `test_unclassified_programmer_exception_propagates_and_requires_recovery_inspection` verifies that an arbitrary `RuntimeError` propagates, leaves the delivery `ATTEMPTING`, is neither `FAILED` nor `UNKNOWN_ACK`, and is not retried automatically. Such a state requires future recovery inspection because no provider-neutral acknowledgement classification was produced.

## 12. Isolation Evidence
No network, database, subprocess, sleeps, credentials, SDKs or gateway imports. Deterministic fake transport only.

## 13. Known Gaps
No provider reconciliation, idempotency ledger, async scheduling, crash injection, or production adapter validation.

## 14. Readiness Impact
B3: `PARTIALLY_ADDRESSED`. Production migration remains **NO-GO**. B1/B2 statuses are unchanged.

The change from generic transport exception → FAILED to classified ambiguous exception → UNKNOWN_ACK is intentional hardening and prevents unsafe duplicate sends.
