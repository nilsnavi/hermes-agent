"""Operations layer for the V2 runtime (Sprint 1.0.6.3).

Read-only canary observability + approval foundation. Sits ON TOP of the
existing execution stack (RunEngine / ExecutionEngine / RecoveryEngine /
ApprovalManager / SQLiteExecutionStore) and NEVER duplicates it:

```
        Gateway V2
             |
      RuntimeOrchestrator
             |
          Store
             |
    +--------+---------+
    |                  |
Observability       Approval Service
|                  |
Run Inspector        Approval Controller
Event Summary        Operator Decisions
Health Metrics       Audit Trail
Manual Review        Recovery Resume
```

Guarantees:

- READ-ONLY by default: every inspection path opens the store read-only
  and never mutates. The only write paths are EXPLICIT operator approval
  decisions (approve / reject / expire) which are operator-identity
  gated, version-guarded, atomic, and appended to the durable audit
  journal.
- No raw payloads: run summaries, timelines, health and metrics expose
  only whitelisted scalar fields — never prompts, raw tool arguments or
  secret-bearing output.
- Stdlib-only: no gateway / scheduler / provider imports at module
  level (the service facade may inject optional callables, e.g. a tool
  metadata lookup for read-only enforcement).
"""
