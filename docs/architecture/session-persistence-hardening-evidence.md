# Sprint 1.5.2 — session persistence hardening evidence

## 1. Scope

Изолированно усилены `hermes_core` contracts. Runtime SessionDB, SQLite/WAL, schema, ownership и публичные runtime API не менялись.

## 2. Baseline

Sprint 1.5.0 оставлял B1/B2 открытыми; Sprint 1.5.1 подтвердил 26 C1–C4 контрактных тестов. Ранее `SessionService` мутировал загруженный объект до `save()` и не имел CAS.

## 3. Persistence Projection

Полная матрица находится в `docs/architecture/session-persistence-projection.md`. Core-owned поля не смешиваются с adapter-owned profile/source/transcript/routing metadata или runtime-only ресурсами.

## 4. Concurrency Contract

`conditional_save(session, expected_generation)` сравнивает durable generation и возвращает immutable `SUCCESS`, `CONFLICT` или `PERSISTENCE_ERROR`. При конфликте запись не перезаписывается. Generation увеличивается только доменным переходом; скрытые increments запрещены.

Generation contract: durable state starts at `G`. A candidate transition may derive
`G+1` before persistence, while `expected_generation` remains `G`. `SUCCESS`
commits `G+1` and returns the committed session supplied by persistence. `CONFLICT`
leaves durable state unchanged and leaves the caller-authoritative object unchanged.
`PERSISTENCE_ERROR` never exposes the candidate as committed. `REJECTED` performs no
persistence and does not advance committed generation. `lease_generation` is an
ownership epoch, distinct from session generation; message/transcript generations in
the runtime are separate concerns and are not conflated with this contract.

## 5. Mutation Safety

Каждый переход использует deep-copied candidate. Только успешный CAS вызывает adoption в caller object. Ошибка или конфликт оставляют исходный объект и durable запись неизменными.

## 6. Lease Fencing

`lease_generation` и owner проверяются доменом, а `generation` — persistence CAS. Stale release/close не могут изменить lease нового владельца.

## 7. Failure Semantics

Application result различает `SUCCESS`, `CONFLICT`, `REJECTED`, `PERSISTENCE_ERROR`; DB exceptions не просачиваются. Legacy `save()` оставлен для C1 compatibility fake, но hardened path требует `conditional_save`.

## 8. Test Evidence

| Contract | Test | Expected | Actual | Result | Evidence | Known limitation |
|---|---|---|---|---|---|---|
| P1 | successful CAS | G→G+1 | passed | PASS | test_session_persistence_hardening.py | in-memory fake |
| P2 | stale writer | conflict, A remains | passed | PASS | same | no multi-process run |
| P3 | persistence failure | source/store unchanged | passed | PASS | same | adapter error simulated |
| P4 | lease+persistence fencing | stale owner blocked | passed | PASS | same | in-memory |
| P5 | stale release | current lease preserved | passed | PASS | same | adapter integration pending |
| P6 | stale close | current session preserved | passed | PASS | same | adapter integration pending |
| P7 | rejection vs conflict | distinct statuses | passed | PASS | same | — |
| P8 | infra vs conflict | distinct statuses | passed | PASS | same | — |
| P9 | projection round-trip | core fields exact | passed | PASS | same | runtime mapping pending |
| P10 | adapter metadata | not claimed by core | passed | PASS | same | adapter metadata simulated |

## 9. Isolation Evidence

Tests use only deterministic in-memory CAS fake; no SQLite, SessionDB, network, subprocess, sleep, credentials or production runtime imports. Existing C1–C4 tests remain unchanged and must continue passing.

## 10. Known Gaps

Real SessionDB adapter implementation, multi-process WAL behavior, route-exception cleanup, delivery recovery and migration wiring remain outside this sprint. B1/B2 are not closed.

## 11. Readiness Impact

B1: `PARTIALLY_ADDRESSED` (core contract hardened; adapter evidence absent). B2: `PARTIALLY_ADDRESSED` (explicit projection and ownership boundary; complete runtime mapping absent). Production migration remains **NO-GO** and this sprint does not authorize adapter migration.
