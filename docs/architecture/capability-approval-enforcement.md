# Capability and approval enforcement

`hermes_core` validates an immutable capability grant before protected execution through `ExecutionService.invoke_protected`; this path has no caller-controlled bypass flag. Legacy `invoke` remains only for existing unprotected C3 compatibility. Grants bind principal, session, turn, tool call, tool name and SHA-256 canonical argument binding; optional approval binds the same identity. Evaluation time is supplied explicitly. Future-issued and expired grants fail closed.

Authorization statuses: `AUTHORIZED`, `DENIED`, `APPROVAL_REQUIRED`, `EXPIRED`, `REVOKED`, `CONTEXT_MISMATCH`, `ARGUMENT_MISMATCH`, `INVALID_GRANT`.

| Condition | Result | Executor called? |
|---|---|---|
| valid grant, no approval | AUTHORIZED | yes |
| valid grant + bound approval | AUTHORIZED | yes |
| missing approval | APPROVAL_REQUIRED | no |
| wrong context/tool | CONTEXT_MISMATCH | no |
| changed arguments | ARGUMENT_MISMATCH | no |
| expired/revoked | EXPIRED/REVOKED | no |
| missing/malformed grant | INVALID_GRANT | no |

Canonical JSON supports JSON-compatible values and uses sorted keys, compact separators, UTF-8 and `allow_nan=False`; unsupported values and non-finite numbers fail closed. Approval lifetime/revocation mapping is UNVERIFIED and durable state remains adapter-owned. Runtime classification of read-only versus mutating tools is PARTIAL/UNVERIFIED. `approved=True` legacy metadata alone never authorizes protected execution. Production runtime remains authoritative and migration is NO-GO.
