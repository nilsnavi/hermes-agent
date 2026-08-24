# SPRINT 1.3.14 — THM / AUTHORITY SEALING CLOSEOUT — COMMIT MANIFEST
#
# ЛИШЬ MANIFEST. НЕ commit / НЕ push / НЕ stage runtime state.
# ПОДГОТОВЛЕНО: closeout-сессия (этот файл — артефакт №44).

## Цель
Limited Auxiliary Service Restart Policy — authority-sealed, hardened, certified.
Sprint 1.3.14 = PASS (A1/A2/A3/A4 + H3 + H5 CLOSED).

## Состав изменений (файлы, кандидаты в commit)

### Source — agent/service_restart_policy/
- registry.py            — A3: immutable per-instance snapshot, REGISTRY_VERSION, registry_digest;
                           authority reads go through instance snapshot (module rebind не меняет существующий runtime)
- runtime.py             — A3: registry_digest capture + REGISTRY_DRIFT check + binding;
                           A1: instance_token в grant + проверка в _consume_execution_grant (cross-instance deny)
- lock.py                — A4: renew требует live-owner (os.getpid — trusted inspector) + _classification==ALIVE;
                           foreign/pid-spoof/nonce-only renewal denied; dead/unknown fail-closed
- models.py              — AdmissionContext.registry_digest (default "")
- approval.py            — ApprovalContract.registry_digest (default "")

Не изменены/не нуждаются: executor.py (уже sealed: требует exact LimitedRestartRuntime + private __runtime_owner),
idempotency.py (coordinator_commit — уже sealed, store passive).

### Tests — tests/service_restart_policy/
- test_executor_authority_boundary.py — переписан под runtime-owned модель: A1 adversarial
  (direct call deny, no-factory surface, hand-made/copy/deepcopy/pickle/reused/cross-instance grant deny, executor-commit impossible)
- test_durable_execution.py            — чинит ссылки на удалённые API; store cannot forge COMMITTED; cross-process exactly-once
- test_live_owner_lock.py              — renew переписан под live-owner (A4)
- test_authority_sealing.py            — НОВЫЙ: A2 (commit coordinator-only, foreign/runtime-token commit deny),
  A3 (immutable registry, module-rebind unchanged, REGISTRY_DRIFT, discovery never grants),
  A4 (real multiprocess foreign renew deny, pid-spoof, dead/unknown renew fail-closed, nonce-alone insufficient)

### Docs
- docs/codemap/codemap.json / .html / .lock — синхронизированы под финальную печать (authority coordinator, immutable snapshot,
  live-owner renew, commit coordinator-owned); lock хэши пересчитаны после последней правки
- docs/hermes-v2/limited-aux-service-restart-policy-1.3.14.md — спецификация спринта
- docs/hermes-v2/limited-aux-service-restart-policy-canonical-delta-1.3.14.json — canonical delta (0 attributable regressions)

## Gate evidence (сверено в closeout)
A1 CLOSED — factory surface absent; only runtime issues grants; copy/deepcopy/pickle/reused/cross-instance deny (adapter=0)
A2 CLOSED — store passive (transition/commit COMMITTED -> PermissionError); coordinator_commit требует exact runtime + token
A3 CLOSED — immutable snapshot; module rebind не меняет existing runtime; registry_digest bound -> REGISTRY_DRIFT
A4 CLOSED — renew live-owner (os.getpid); real multiprocess foreign renew -> False
H3 CLOSED — trusted clock (не входило в данное изменение; подтверждено existing tests)
H5 CLOSED — claim-first atomic idempotency (20-contender + 100 races GREEN)
Independent review blocking_findings = 0
Targeted: 931 passed, 0 failed (§32 наборы)
Concurrency: GREEN; shadow 120/120 correctness=100%, mutation=0; rehearsal 240, violations=0
Clean snapshot: COMPILE_OK, IMPORT_OK, runtime-state dependency=0, restart/authority GREEN
Canonical: attributable NEW failures = 0; registry size = 1 (hermes-aux-canary.service)
Production mutation = 0; secret findings = 0

## НЕ включено / НЕ делать
- НЕ начинать Sprint 1.3.14.1
- НЕ commit/push (этот файл — только манифест)
- НЕ выполнять restart/reload/stop/start/signal; canary не трогать
- НЕ расширять registry; НЕ включать SYSTEM_CONTROL / generic SERVICE_CONTROL
