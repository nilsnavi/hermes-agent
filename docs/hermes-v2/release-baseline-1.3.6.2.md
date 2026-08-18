# Release Baseline — Sprint 1.3.6.3 (hermes-v2-pre-prod-canary-1.3.6.2)

Immutable Git baseline для Hermes 2.0 перед первым production canary (Sprint 1.3.7).

## Baseline identifiers

| Поле | Значение |
|---|---|
| BASELINE_COMMIT_SHA | `8dfe9b3c82475e42e82e82fd1071991ad6e395ff` |
| BASELINE_TAG | `hermes-v2-pre-prod-canary-1.3.6.2` |
| BASELINE_TAG_SHA | `8dfe9b3c82475e42e82e82fd1071991ad6e395ff` (tag → commit) |
| ROLLBACK_BASELINE_SHA | `8dfe9b3c82475e42e82e82fd1071991ad6e395ff` |
| Branch | `main` (ahead 2 от origin) |
| Parent | `83ce2c55a` (Sprint 1.1.1.1/1.1.1.2 upstream HEAD) |
| Commit message | `feat(hermes-v2): зафиксировать безопасный baseline перед production canary` |

## Состав commit (180 файлов, +29690/−2)

- **RUNTIME (83)**: `agent/sandbox_runtime/` (30), `agent/system_boundary/` (25),
  `agent/verified_tool_executor/` (11), `agent/capability_router/` (9),
  `agent/operational_search/` (6), `agent/intent_router/{enforcement,acceptance_matrix}.py` (2)
- **TESTS (73)**: `tests/sandbox_runtime/`, `tests/system_boundary/`,
  `tests/verified_tool_executor/`, `tests/operational_search/`,
  `tests/intent_router/` (untracked-new), `tests/scripts/test_run_tests_exit_contract.py`
- **DOCS (23)**: `docs/hermes-v2/` (20), `docs/codemap/` (3: lock/json/html)
- **RUNNER (2)**: `scripts/run_tests.sh` (fail-red exit marker + контракт-документация),
  `.gitignore` (`/scripts/tests/` generated-dup + стандартные исключения)

**НЕ включено** (осознанно): 22 pre-existing modified tracked-файла
(`gateway/run.py`, `gateway/platforms/api_server.py`, `agent/gateway_v2/*`,
`agent/intent_router/*` tracked, `tests/{gateway_v2,intent_router}/*`, `AGENTS.md`,
`package-lock.json`) — остаются незакоммиченными изменениями рабочего дерева;
`scripts/tests/` (3030 байт-идентичных дублей `tests/` — ignored);
`/tmp`-артефакты; бэкапы; state.db/WAL/SHM; логи; кэши; секреты.

## Тестовые результаты (Sprint 1.3.6.2/1.3.6.3)

- Fresh targeted gate (5 scope + runner contract): **82 files, 1033 passed, 0 failed, exit 0**
- Reproducibility snapshot (`~/hermes-release-baseline-sprint1.3.6-20260818-110429/`):
  538 файлов, SHA256SUMS verify 100%, canonical runner из snapshot 618/618
- Full canonical raw: 2966 files, 32472 passed, 14 failed, 210 skipped
  → **TEST_RUNNER_EXIT_CODE=1 / FULL_CANONICAL_EXIT=1** (fail-red контракт)
- Failure classification: 10 файлов PRE-EXISTING (empty git diff), 1 ENVIRONMENTAL
  (calibration_safety — изолированно 13/13), 3 FLAKY (retry-passed в том же прогоне),
  1 contention-timeout (test_cli — изолированно 9/9)
- **NEW_REGRESSIONS=0**
- Certification: PASS_WITH_BASELINE

## Production state на момент baseline

| Проверка | Значение |
|---|---|
| DB quick_check | ok |
| DB foreign_key_check | 0 rows |
| DB journal_mode | wal |
| Gateway MainPID / NRestarts | 323 / 0 |
| Gateway ActiveState / SubState | active / running |
| ExecMainStatus | 0 |
| Scheduler | 22 jobs, sorted_ids_hash `6c7f478d36815c85` |
| Provider inventory | `bd1063cd6d047c0a…` (без изменений) |
| config.yaml | `27b74c8cf3d0bc4e…` (без изменений) |
| Production mutations | 0 |
| SYSTEM_CONTROL | OFF |
| Security findings (snapshot + staged diff) | 0 реальных (только тест-фикстуры) |

## Source manifest reference

`/tmp/hermes-source-manifest-1.3.6.2.json` (203 записи: path/status/sha256/category/
sprint_origin/tracked/required_for_runtime/required_for_tests). Копия включена в
release snapshot.

## Rollback reference

`ROLLBACK_BASELINE_SHA=8dfe9b3c82475e42e82e82fd1071991ad6e395ff` — для Sprint 1.3.7
любой canary-diff считается относительно этого SHA. Откат сейчас НЕ выполняется.

## Push status

НЕ запушено (ожидает явной команды). Команды:
`git push origin main`
`git push origin hermes-v2-pre-prod-canary-1.3.6.2`

## UPSTREAM DIVERGENCE AT CANARY CUT (Sprint 1.3.6.4.1)

- Certified baseline SHA: `8dfe9b3c82475e42e82e82fd1071991ad6e395ff`
- origin/main SHA on cut: `8505559fa94e35f09f17fd29c228b74fb4acdda1` (на момент 1.3.6.4;
  upstream продолжал двигаться: `4bdddf4e9…` на 1.3.6.4.1 pre-flight)
- merge-base: `a4f468e83`; ahead=2; behind=1612 (на момент 1.3.6.4)
- Timestamp: 2026-08-18

**Sprint 1.3.7 intentionally branches from the certified baseline,
NOT from current origin/main.**

Причина: rebase/merge 1612 upstream commits инвалидировал бы certification
evidence (NEW_REGRESSIONS=0, 1033/1033 targeted, canonical raw result,
release snapshot 538/538).

## IMPORTANT FUTURE RULE (Sprint 1.3.6.4.1 §12)

Upstream synchronization после 1.3.7 — ОТДЕЛЬНЫЙ спринт. Автоматический
перенос 1612 commits в canary runtime запрещён. Будущий процесс:

1. new upstream integration branch
2. merge/rebase/cherry strategy review
3. full certification
4. new baseline

НЕ сейчас. origin/main остаётся READ-ONLY для этого спринта.
