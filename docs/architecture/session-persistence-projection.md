# Session persistence projection

Sprint 1.5.2 анализирует текущий gateway/SessionDB как авторитетный runtime и фиксирует узкую границу `hermes_core`. Core моделирует только идентичность, ключ, lifecycle, lease fencing, generation, parent lineage и объявленные metadata. SQLite, WAL, routing-home, transcript, counters, profile/source columns, process handles и cleanup resources принадлежат runtime/adapters.

| Runtime field/state | Current owner | Core representation | Persistence requirement | Migration relevance | Status |
|---|---|---|---|---|---|
| session id | SessionDB/SessionEntry | SessionId | exact round-trip | identity mapping | CORE_OWNED |
| session key | gateway session key builder | SessionKey | exact round-trip | routing lookup | CORE_OWNED |
| profile/source/chat/thread/origin | gateway adapter and SessionDB | absent | adapter preserves | adapter mapping | ADAPTER_OWNED |
| lifecycle active/closed | SessionDB/SessionStore | SessionStatus | conditional transition | adapter translation | CORE_OWNED |
| generation | runtime durable session/message generations | int | expected-generation CAS | B1 contract | CORE_OWNED |
| lease owner/generation | turn lease tables and gateway state | lease_owner/lease_generation | lease and persistence fencing | B1 contract | CORE_OWNED |
| parent session id | SessionDB | SessionId? | exact lineage value | migration mapping | CORE_OWNED |
| metadata map | core boundary | dict[str,str] | deep-copy round-trip | explicit only | CORE_OWNED |
| started/updated/expiry/resume/suspended flags | SessionDB/gateway | absent | adapter-owned persistence | deferred | ADAPTER_OWNED |
| transcript/messages/FTS/compression | SessionDB/message mixins | absent | runtime storage | deferred | ADAPTER_OWNED |
| routing-home/index and profile DB path | session persistence adapter | absent | adapter-only | deferred | ADAPTER_OWNED |
| SQLite handles, WAL, registry generations | SessionDB/registry | absent | runtime resource ownership | out of scope | RUNTIME_ONLY |
| process ContextVars/run_generation/worker resources | gateway/application process | absent | never persisted by core | out of scope | RUNTIME_ONLY |

`SessionService` acquire/release/close now derive an isolated candidate, conditionally persist it, and adopt it only after success. The existing runtime still owns SessionDB and its schema. `RuntimeApplication.plan` acquires before routing and `finish` releases; route-exception cleanup is observed as an unresolved runtime concern and is not changed by this sprint.

Generation semantics are explicit: a durable session begins at `G`; a candidate may
derive `G+1` before the CAS call, but the expected generation remains `G`. Success
commits `G+1`; conflict preserves durable and caller state; persistence failure does
not commit the candidate; domain rejection performs no persistence. Lease generation
is an ownership epoch, separate from session generation and from message/transcript
generation maintained by the authoritative runtime.
