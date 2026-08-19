# Service Reload Registry — Sprint 1.3.11

## Registered profiles (static, immutable, versioned)
- **hermes-aux-canary**: unit hermes-aux-canary.service, HERMES_AUXILIARY, LOW,
  exec `/bin/kill -HUP $MAINPID` (reload semantics, same-PID), blast SERVICE,
  consumer NONE, rollback=reload-previous-config. Source fixtures in
  `agent/service_reload_canary/fixtures/`.

## Admission contract
Every service must pass full_admit: class AUXILIARY, criticality<=MEDIUM,
identity VERIFIED, graph HEALTHY, critical_dependents=0, blast<=SERVICE,
consumer NONE/PASSIVE, ExecReload reload-only, validator+health+rollback present.

## Denied classes / services
HERMES_CORE, DATASTORE, SCHEDULER, PROVIDER, NETWORK, SECURITY, EXTERNAL, UNKNOWN;
hermes-gateway, postgres, redis, scheduler, provider runtime, SSH/VPN/firewall,
Docker runtime, auth/secrets services. Never admitted.

## Runtime authority
Registry is authoritative. Runtime discovery may verify/invalidate/raise-risk/disable,
never grant.