# Service Reload Runbook — Sprint 1.3.10

## Preconditions
- mode=canary, enabled=true, budget available
- explicit operator approval bound to service_id/profile_version/identity/graph/config/health/intent
- hermes-gateway never touched (SELF_CONTROL_FORBIDDEN)

## Procedure (operator-approved, one at a time)
1. identity/graph/validator/pre-health revalidate
2. single-use approval validate
3. budget attempt + service lock
4. `systemctl --user reload <allowlisted-unit>` (adapter=1) — reload ONLY
5. post-reload verify + stabilization window health
6. COMMIT; replay intent → adapter=0

## Failure
UNKNOWN_OUTCOME → retry=0, MANUAL_REVIEW. Rollback via proved non-restart recovery only.

## Kill switch
After validation: mode=off / enabled=false → reload request CANARY_DISABLED, adapter=0.

## NOTE
This canary is NOT generic SERVICE_CONTROL. STOP/START/RESTART remain denied.
