# Service Eligibility Policy — Sprint 1.3.9

Strict precedence (fail-closed):
1. self-control prohibition → deny
2. service class hard deny (core/datastore/scheduler/provider/network/security/external/unknown)
3. identity verification (VERIFIED required)
4. graph health (STALE/UNAVAILABLE/CORRUPT → deny)
5. operation support
6. config validator presence
7. health contract presence
8. rollback proof (strategy != unsupported)
9. blast radius (static ceiling AND dynamic dependents → deny)
10. criticality · 11. risk · 12. approval · 13. rollout · 14. future-canary eligibility

Eligibility enum includes ELIGIBLE_FOR_FUTURE_RELOAD_CANARY /
ELIGIBLE_FOR_FUTURE_RESTART_CANARY — **NOT** permission to execute. Only
HERMES_AUXILIARY with verified identity, healthy graph, service-only blast,
present health+validator, proven rollback reaches future-canary eligibility.
Execution in Sprint 1.3.9 is always DENIED.
