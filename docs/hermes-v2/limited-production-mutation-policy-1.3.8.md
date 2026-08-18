# Limited Production Mutation Policy — Sprint 1.3.8

## Authority model
NO generic write authority. A mutation is allowed only for:
**profile + registered target + exact resolved identity + typed operation + approval**.

Policy layer is an ADDITIONAL constraining layer over CapabilityPolicyEngine /
SystemBoundaryLayer / VerifiedToolExecutor / TransactionalPipeline. It can
DENY / REQUIRE_APPROVAL / REQUIRE_REVALIDATION / RAISE_RISK / REDUCE_BUDGET.
It CANNOT grant authority, lower risk, bypass SBL/approval/executor, increase
blast radius, or enable SYSTEM_CONTROL.

## Hard deny (always)
SYSTEM_CONTROL, SYSTEM_WRITE_ANY, SERVICE_CONTROL/RESTART/RELOAD, PROCESS_SIGNAL,
PACKAGE/NETWORK/FIREWALL/ROUTING/CRON/SCHEDULER/PROVIDER/SSH/USER/DATABASE/DOCKER/SYSTEMD
change + `~/.hermes/config.yaml`, `~/.hermes/state.db`, `~/.hermes/.env`,
`~/.ssh/*`, `/etc/*`, `/usr/*`, `/var/lib/*`, `/run/*`, `/proc/*`, `/sys/*`, `/dev/*`.

## Enforcement
`agent/production_policy/` reuses canary mechanisms (atomic_write, lock, snapshot)
and adds: immutable profiles, target registry, typed operations, risk/blast-radius/
consumer classification, durable budget, failure circuit breaker, per-profile
verifier, byte-for-byte rollback, UNKNOWN_OUTCOME retry=0, kill switch.

## Production authority after Sprint 1.3.8
Limited to registered Hermes-owned resource profiles (marker/json/text) under
`~/.hermes/managed/resources/`. **SYSTEM_CONTROL stays OFF. Service control DENIED.**
Kill switch: ON after validation.
