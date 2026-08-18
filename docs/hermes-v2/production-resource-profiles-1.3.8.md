# Production Resource Profiles — Sprint 1.3.8

Immutable, versioned profiles. Change of authority = new version, never silent
mutation. Effective risk is monotonic (>= profile risk); any uncertain consumer
raises risk.

| id | class | capability | operation | risk | budget (per hour) |
|----|-------|-----------|-----------|------|-------------------|
| P1-MARKER | marker | HERMES_MANAGED_MARKER | SET_MARKER | low_mutation | 3 success / 5 attempts |
| P2-JSON | json | HERMES_MANAGED_JSON | UPDATE_JSON | low_mutation | 3 / 5 |
| P3-TEXT | text | HERMES_MANAGED_TEXT | REPLACE_TEXT | low_mutation | 3 / 5 |

## P1 MARKER — SET_MARKER
Enum-only payload (ENABLED/DISABLED/PAUSED/READY), max 256 B, marker dir
`~/.hermes/managed/resources/markers/`, mode 600. Safest profile.

## P2 JSON — UPDATE_JSON
Schema-controlled JSON, max 16 KB, nesting<=8, bounded keys, atomic write,
valid-JSON+schema+semantic-hash verifier, dir `.../json/`, mode 600.

## P3 TEXT — REPLACE_TEXT
UTF-8 only, max 16 KB, no NUL/binary/overlong, shebang forbidden, not executable,
mode 600/640, dir `.../text/`.

## Target registration (exact, no glob/prefix)
Target resolved identity (realpath, owner, mode) binds to a profile. Name
validator: `^[a-z0-9][a-z0-9._-]{0,63}$`; `..`/`/`/`\`/control/unicode-confusable
denied; realpath-boundary enforced. Child names only via strict rules.

## Consumer classes
NO_RUNTIME_CONSUMER / PASSIVE_READ_CONSUMER / ACTIVE_CONSUMER / UNKNOWN.
Sprint 1.3.8 allows mutation only for NO_RUNTIME_CONSUMER (or proven passive);
ACTIVE/UNKNOWN → DENY. Consumer drift → PROFILE_CONSUMER_CHANGED → rollback/disable.

## Blast radius
1.3.8 only `blast_radius <= RESOURCE_ONLY`. SERVICE/MULTI/HOST/NETWORK/UNKNOWN → DENY.
