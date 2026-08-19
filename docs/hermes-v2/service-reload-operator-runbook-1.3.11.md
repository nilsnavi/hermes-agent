# Service Reload Operator Runbook — Sprint 1.3.11

## Preconditions for a live reload
- mode=limited, flag on, budget available, breaker closed, kill-switch off
- service admitted + registered + enabled
- explicit approval bound to service_id/version/identity/graph/consumer/config/
  health/risk/blast/rollback/baseline/plan/TTL (single-use)
- preflight: identity VERIFIED, graph HEALTHY, blast<=SERVICE, consumer allowed,
  validator VALID, pre-health HEALTHY, rollback proven

## Execute one reload
`systemctl --user reload <registered-aux>` via profile-bound adapter (no caller
arbitrary args). Verify: unit identity unchanged, PID semantics per profile, service
active, no orphans, ports/health ok. Stabilization window T+0/2/5/10 all pass. → COMMITTED.

## Idempotency
Replay of the same intent returns prior result (durable), adapter=0.

## Failure handling
- UNKNOWN_OUTCOME → retry=0, breaker opens, manual review.
- Verify/health fail → rollback via proven non-restart mechanism, else MANUAL_REVIEW.
- Never use restart as rollback (restart authority denied).

## Kill-switch
After validation set gate OFF; all reloads → POLICY_KILLED. Verify SYSTEM_CONTROL=OFF,
generic SERVICE_CONTROL=DENIED, restart=DENY.