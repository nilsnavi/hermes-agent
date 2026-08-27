# Phase 8.5.1 — Durable Shadow Socket Permission Hardening & Derivative Baseline

## Objective
Make `agent/shadow_worker/transport.py` (`UnixDatagramShadowTransport`) create the
one-way transport socket with durable least-privilege ownership and mode:

```
socket: owner = runtime uid (hermes-shadow), group = hermes-shadow-tap, mode = 0660
spool : 0750 (operator-previsioned; worker never broadens it)
```

without manual chmod/chgrp after restart, ExecStartPost, world-writable perms, or any
stored sudo password. Then certify a NEW derivative Shadow Worker baseline on top of
`1002cc48daa7015a069b83b1a490261d792e8cee`.

## Why (P8.5 blocker)
The previous bind left the socket as `hermes-shadow:hermes-shadow srwxr-xr-x` (process
umask), so a manual `chgrp hermes-shadow-tap` + `chmod 0660` did NOT survive a worker
restart. This hardens the **creation path itself**.

## Change (single module + manifest)
- `agent/shadow_worker/transport.py`
  - `_resolve_tap_gid(group)` — resolve GID by canonical name via `grp.getgrnam`;
    empty/missing group → `SocketGroupNotFound` (typed `SOCKET_GROUP_NOT_FOUND`),
    fail-closed **before** any socket is created.
  - `_unlink_stale_socket_safely(path)` — only unlink a pre-existing **real Unix
    socket** (`lstat`); symlink / regular file / directory → `SocketPermissionError`
    (`STALE_SOCKET_UNSAFE`), object left untouched.
  - `_enforce_socket_inode(path, gid)` — after `bind`, apply `os.chown(path, -1, gid)`
    + `os.chmod(path, 0o660)` (path-based: `fchmod` is a no-op for AF_UNIX sockets on
    Linux), then verify with `stat`: same inode (TOCTOU guard), `mode & 0o777 == 0o660`,
    `st_gid == gid`, `st_uid == os.getuid()`. Any mismatch → fail closed + partial
    socket unwound (only a socket WE bound is unlinked).
  - `UnixDatagramShadowTransport.__init__(path, *, tap_socket_group="hermes-shadow-tap")`
    wires the above; the transport is NOT exposed as ready unless verification passes.
  - Only stdlib used (`grp`, `os`, `socket`, `stat`); no subprocess/groupadd/usermod/
    systemctl/chgrp-command/sudo surface.
- `release/shadow-worker-8.3/{manifest.json,config-example.json,SHA256SUMS}` — phase
  8.5.1, `parent_worker_baseline=1002cc48…`, new `transport.py` sha256, config keys
  `tap_socket_group`/`tap_socket_mode`(0660).
- `tests/shadow_worker/test_socket_permissions.py` — 16 tests covering §13 + restart
  durability (rebind + real subprocess worker-restart simulation).

## Gates (all green)
- `compileall` OK; scoped canonical `tests/shadow_worker` → PASS (exit 0).
- Full canonical: NEW_REGRESSIONS=0 (scoped module never in failing/collection sets).
- AST/security gate: forbidden-surface grep clean; mechanical `scan_shadow_worker.py`
  GATE PASS (UNAUTHORIZED_EXECUTION_PATHS=0, WORKER_TO_PRODUCTION_CHANNELS=0,
  GATEWAY_RUNTIME_COUPLING=0, FILESYSTEM_MUTATION=0).
- Independent security review: BLOCKING_FINDINGS=0.

## Derivative baseline
```
tag = hermes-v2-shadow-worker-durable-socket-phase8.5.1
parent = 1002cc48daa7015a069b83b1a490261d792e8cee
```
Publication to fork `nilsnavi/hermes-agent` only; no force. DO NOT deploy/restart the
production worker or gateway (Phase 8.5.2).