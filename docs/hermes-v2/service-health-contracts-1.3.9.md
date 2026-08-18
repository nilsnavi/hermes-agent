# Service Health Contracts — Sprint 1.3.9

Read-only supported checks: systemd state, process identity, PID, port listening
(local only, exact expected bindings, no public discovery authority), local HTTP
health, local UNIX socket, file marker, provider-independent runtime probe. No
arbitrary shell.

Results: HEALTHY / DEGRADED / UNHEALTHY / UNKNOWN. UNKNOWN → future eligibility
DENY. Future mutation requires HEALTHY precondition and HEALTHY postcondition
with stabilization window.

Config validation is read-only and bounded (timeout, output cap, no secrets, no
mutation): VALID / INVALID / UNKNOWN / TIMEOUT / UNAVAILABLE. Only VALID
supports future eligibility. LLM cannot define validator authority; unknown
validator → CONFIG_VALIDATOR_MISSING.
