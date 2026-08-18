# Production Mutation Budgets — Sprint 1.3.8

## Durable per-hour budget (per profile, persisted)
- max_successful_mutations_per_hour = 3 (per profile)
- max_attempts_per_hour = 5
- max_rollbacks_per_hour = 3
- max_failures_per_hour = 5

## Global budget
- global successful max = 10/hour

Exhaustion → `BUDGET_EXCEEDED`, adapter_calls = 0.

## Failure circuit breaker (per profile)
Auto-disable after: 2 consecutive verification failures, or 2 health failures,
or 1 rollback failure, or 1 UNKNOWN_OUTCOME.
Global kill-switch on: rollback false-success, boundary bypass, unknown-resource
mutation, non-allowlisted-target mutation.

## Budget drill (sandbox-proven)
Synthetic budget limit reached → next operation `BUDGET_EXCEEDED`, adapter=0.
Circuit-breaker drill → profile auto-disabled, unrelated profiles untouched.

## Sprint 1.3.8 live counters
- limited_prod_successful_mutations = 2 (market marker + json) <= 5
- non_policy_production_mutations = 0
- rollback false-success = 0, UNKNOWN_OUTCOME retries = 0, duplicate = 0,
  blast_radius_violation = 0.

Kill switch after validation: ON (all profiles blocked).
SYSTEM_CONTROL stays OFF.
