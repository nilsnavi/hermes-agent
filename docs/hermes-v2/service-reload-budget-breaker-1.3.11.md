# Service Reload Budget & Breaker — Sprint 1.3.11

## Budget (durable, survives restart)
- Global: max_attempts/hour=8, max_success/hour=5.
- Per-service: max_success/hour=2, max_attempts/hour=3, max_rollback/hour=1.
- Reservation: attempt slot reserved durably before adapter; released on pre-exec deny;
  consumed on real adapter call; success consumed on commit. No race can exceed budget.

## Circuit breaker (per-service, durable)
Opens on: 1 UNKNOWN_OUTCOME · 1 rollback failure · 2 consecutive verify failures ·
2 consecutive health failures · identity/graph drift during active plan.
When open, requests → BREAKER_OPEN, adapter=0.

## Global kill-switch
On: wrong-service mutation, generic service mutation, blast radius violation,
self-control bypass, rollback false-success. All registered reloads → POLICY_KILLED,
adapter=0. SYSTEM_CONTROL stays OFF; generic SERVICE_CONTROL stays DENIED.