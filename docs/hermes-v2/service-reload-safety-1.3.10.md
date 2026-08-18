# Service Reload Safety — Sprint 1.3.10

## Hard denies (P0)
- RESTART / STOP / START / KILL / SIGNAL / DAEMON-RELOAD → SERVICE_OPERATION_DENIED, adapter=0.
- hermes-gateway: reload/restart/stop/kill/signal → SELF_CONTROL_FORBIDDEN.
- Non-allowlisted service mutation → SERVICE_NOT_ALLOWLISTED.

## Reload safety gates
identity VERIFIED · graph HEALTHY · blast <= SERVICE · config validator VALID · pre-health HEALTHY · explicit single-use approval · durable budget (≤2 success / ≤3 attempts / ≤1 rollback) · idempotency (replay adapter=0).

## Rollback
No restart-as-rollback. Rollback only via proved non-restart recovery; restart-based recovery → MANUAL_REVIEW_REQUIRED.
