# Offline session projection parity evidence

Phase 0 only. Production runtime remains authoritative; production migration is **NO-GO**. No production `HERMES_HOME`, SessionDB, gateway wiring, ownership transfer, provider/tool/delivery effect, network, credential or production database was used.

## Historical Sprint 1.5.7 provenance

| Classification | Total |
|---|---:|
| MATCH | 0 |
| INTENTIONAL_DELTA | 0 |
| UNVERIFIED | 23 |
| NOT_APPLICABLE | 1 |

## Historical Sprint 1.5.10 — offline projection baseline

This section is the original Sprint 1.5.10 evidence only. The authoritative source was `hermes_state.SessionDB`, using temporary `tmp_path` storage and a read-only handle. The projection boundary was `project_detached`; adapter-owned metadata stayed outside the core object.

### Validation receipts

- Focused: `C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra` — 24 passed, 0 failed, 0 skipped, 1 `PytestCacheWarning`, 10.35s.
- Full core: `C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra` — 206 passed, 0 failed, 0 skipped, 1 `PytestCacheWarning`, 28.66s.
- Compileall: `C:\Python314\python.exe -m compileall hermes_core` — PASS.
- Canonical: 12 files, 206 tests passed, 0 failed, 100% complete, 19.1s, 24 workers.

### Scenario results

| Scenario | Result | Historical evidence |
|---|---|---|
| SP1 normal active/open | MATCH | Real temporary `SessionDB.get_session("s1")`, detached projection and identity equivalence |
| SP2 parent lineage | UNVERIFIED | No parent-child fixture or lineage assertion in Sprint 1.5.10 |
| SP19 source unchanged/no-write | MATCH | Real temporary SessionDB read/projection with unchanged digest |
| SP20 multiple-session isolation | UNVERIFIED | No multi-session fixture or isolation assertion in Sprint 1.5.10 |

### Sprint 1.5.10 parity totals

| Classification | Total |
|---|---:|
| MATCH | 2 |
| INTENTIONAL_DELTA | 0 |
| UNVERIFIED | 18 |
| NOT_APPLICABLE | 0 |

Sprint 1.5.10 conclusion: SP1 and SP19 were the two MATCH observations. SP2 and SP20 remained unresolved. B1 and B2 remained `PARTIALLY_ADDRESSED`; P and B remained `PARTIAL`. Phase 0 was `AUTHORIZED`; Phase 1–4 were `NOT_AUTHORIZED`; production migration was **NO-GO**.

## Sprint 1.5.11 — parent lineage and multi-session isolation

Canonical baseline: `f10c861897ab1f136764e0c6cf80a0d844e505f5`. The real legacy source remained `hermes_state.SessionDB`; temporary parent/child and three-session fixtures used the actual SessionDB APIs. The detached projection, metadata isolation and digest no-write checks were executed against temporary storage.

### Validation receipts

- Focused: `C:\Python314\python.exe -m pytest tests/hermes_core/test_offline_session_projection_parity.py --confcutdir=tests/hermes_core -q -ra` — 26 passed, 0 failed, 1 `PytestCacheWarning` (WinError 183), 11.60s.
- Full core: `C:\Python314\python.exe -m pytest tests/hermes_core --confcutdir=tests/hermes_core -q -ra` — 208 passed, 0 failed, 1 `PytestCacheWarning` (WinError 183), 11.60s.
- Compileall: `C:\Python314\python.exe -m compileall hermes_core` — PASS.
- Canonical: 12 files, 208 tests passed, 0 failed, 100% complete, 36.1s, 24 workers, using `HERMES_PYTHON=/c/Python314/python.exe`.
- Safe legacy selector: `C:\Python314\python.exe -m pytest tests/tui_gateway/test_session_resume_db_ownership.py -q -ra` — COLLECTION ERROR, 0 behavioral tests executed, `ModuleNotFoundError: No module named 'concurrent_log_handler'` through `tui_gateway/server.py → agent/conversation_loop.py → hermes_logging.py`. This is an infrastructure/collection blocker, not a behavioral assertion failure.

### Scenario results

| Scenario | Result | Executed evidence |
|---|---|---|
| SP2 parent lineage | MATCH | `SessionDB.create_session(..., parent_session_id="parent")`, authoritative `get_session()`, legacy child parent ID equals detached core parent ID, non-self lineage, detached metadata and unchanged digest |
| SP20 multiple-session isolation | MATCH | Three real SessionDB sessions, independent reads/projections, distinct identities/keys/profiles, metadata mutation isolation, repeated projection equivalence and unchanged digest |

### Sprint 1.5.11 targeted totals

| Classification | Total |
|---|---:|
| MATCH | 2 |
| INTENTIONAL_DELTA | 0 |
| UNVERIFIED | 0 |
| NOT_APPLICABLE | 0 |

### Current SP1–SP20 totals after Sprint 1.5.11

| Classification | Total |
|---|---:|
| MATCH | 4 |
| INTENTIONAL_DELTA | 0 |
| UNVERIFIED | 16 |
| NOT_APPLICABLE | 0 |

## Readiness impact

- B1 — `PARTIALLY_ADDRESSED`; read/projection parity does not prove transactional mutation fencing.
- B2 — `PARTIALLY_ADDRESSED`; parent lineage and multi-session isolation improve evidence, but complete runtime field preservation remains unproven.
- P — `PARTIAL`; four bounded MATCH observations do not establish global parity.
- B — `PARTIAL`; the safe legacy selector remains blocked and performance/operational evidence is incomplete.

Phase 0 is `AUTHORIZED` for offline/isolated validation only. Phase 1, Phase 2, Phase 3 and Phase 4 are `NOT_AUTHORIZED`. Production migration remains **NO-GO**.
