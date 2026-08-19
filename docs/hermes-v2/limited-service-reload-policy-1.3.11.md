# Limited Service Reload Policy — Sprint 1.3.11

A small static registry of reloadable Hermes auxiliary services. Reload-only authority;
RESTART/STOP/START/KILL/SIGNAL/DAEMON_RELOAD stay DENIED. SYSTEM_CONTROL stays OFF;
generic SERVICE_CONTROL stays DENIED.

## Authority chain
CapabilityPolicyEngine → VerifiedToolExecutor → SystemBoundaryLayer →
LimitedProductionMutationPolicy → ServiceFoundation → **LimitedServiceReloadPolicy** →
ReloadTransaction → ExactReloadAdapter → Verify → StabilizationHealth → Commit/Rollback.

## Admission gate
Auxiliary only; criticality <= MEDIUM; identity VERIFIED; graph HEALTHY; blast <= SERVICE;
no critical dependents; ExecReload exists & is reload (not restart); validator exists; health
contract complete; rollback proven; consumer NONE or PASSIVE. Any miss → NOT_ADMITTED.

## Registry
MAX_REGISTERED=3. Static only; runtime discovery verifies/invalidates, never grants.

## Budget
Global: 8 attempts/h, 5 success/h. Durable; survives restart.

## Circuit breaker
Opens per-service on 1 UNKNOWN_OUTCOME, 1 rollback fail, 2 consecutive verify/health fails.
Global kill-switch on wrong-service/generic mutation, blast violation, self-control bypass,
rollback false-success.

## Durable lock & idempotency
Cross-process per-service lock (owner/nonce/TTL, stale release if owner dead). Durable
idempotency key → replay after process restart returns prior result, adapter=0.

## Production authority
RELOAD only, registered Hermes auxiliary services only. Restart remains DENIED.