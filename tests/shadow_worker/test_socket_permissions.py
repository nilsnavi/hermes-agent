"""Durable socket permission tests (Phase 8.5.1).

UnixDatagramShadowTransport now enforces, by construction:
  group = <tap_socket_group>   (default "hermes-shadow-tap", fail-closed if absent)
  mode  = 0660                 (exactly; no other bits)
  owner = runtime uid          (unchanged)
verified with fstat after bind, and the transport is NOT exposed as ready unless
the verification succeeds.  Stale paths are only unlinked when they are a real
Unix socket (protects against symlink / regular-file replacement).
"""

from __future__ import annotations

import grp
import os
import socket
import stat
import subprocess
import sys
import time

import pytest

from agent.shadow_worker import transport as tr
from agent.shadow_worker.transport import (
    SocketGroupNotFound,
    SocketPermissionError,
    UnixDatagramShadowTransport,
)


def _current_group() -> str:
    return grp.getgrgid(os.getgid()).gr_name


def _assert_tap_inode(path: str, exp_gid: int) -> None:
    st = os.stat(path)  # follows symlink => would point elsewhere if replaced
    assert stat.S_ISSOCK(st.st_mode)
    assert (st.st_mode & 0o777) == 0o660, oct(st.st_mode & 0o777)
    assert st.st_gid == exp_gid
    assert st.st_uid == os.getuid()


# -- group resolution -----------------------------------------------------


def test_group_resolution_success(tmp_path):
    gid = tr._resolve_tap_gid(_current_group())
    assert isinstance(gid, int)
    assert gid == os.getgid()


def test_group_resolution_missing_fails_closed():
    with pytest.raises(SocketGroupNotFound) as ei:
        tr._resolve_tap_gid("__no_such_group_8_5_1__")
    assert "SOCKET_GROUP_NOT_FOUND" in str(ei.value)


def test_group_resolution_empty_fails_closed():
    with pytest.raises(SocketGroupNotFound):
        tr._resolve_tap_gid("")
    with pytest.raises(SocketGroupNotFound):
        tr._resolve_tap_gid(None)  # type: ignore[arg-type]


def test_missing_group_blocks_startup_no_socket(tmp_path):
    path = str(tmp_path / "blocked.sock")
    with pytest.raises(SocketGroupNotFound):
        UnixDatagramShadowTransport(path, tap_socket_group="__no_such_group_8_5_1__")
    # fail-closed: no socket inode left behind
    assert not os.path.exists(path)


# -- durable mode / group / owner (real fchown, no root) ----------------


def test_socket_mode_exact_0660(tmp_path):
    path = str(tmp_path / "mode.sock")
    t = UnixDatagramShadowTransport(path, tap_socket_group=_current_group())
    try:
        _assert_tap_inode(path, os.getgid())
    finally:
        t.close()


def test_socket_owner_unchanged(tmp_path):
    path = str(tmp_path / "owner.sock")
    t = UnixDatagramShadowTransport(path, tap_socket_group=_current_group())
    try:
        st = os.stat(path)
        assert st.st_uid == os.getuid()
    finally:
        t.close()


def test_post_bind_verification(tmp_path):
    path = str(tmp_path / "verify.sock")
    t = UnixDatagramShadowTransport(path, tap_socket_group=_current_group())
    try:
        _assert_tap_inode(path, os.getgid())  # stat AFTER bind: group+mode applied
        assert t.queue_depth() >= 0  # transport exposed only after success
    finally:
        t.close()


def test_default_tap_group_name_applies_exact(tmp_path, monkeypatch):
    # Make the certified default group name resolve to a gid the runner can own
    # (current gid), proving the EXACT "hermes-shadow-tap" path is applied.
    import collections
    entry = collections.namedtuple("grp_struct", "gr_name gr_gid gr_mem")

    def fake_getgrnam(name: str):
        if name == "hermes-shadow-tap":
            return entry("hermes-shadow-tap", os.getgid(), ["hermes-shadow", "hermes"])
        raise KeyError(name)

    monkeypatch.setattr(tr.grp, "getgrnam", fake_getgrnam)
    path = str(tmp_path / "default.sock")
    t = UnixDatagramShadowTransport(path, tap_socket_group="hermes-shadow-tap")
    try:
        _assert_tap_inode(path, os.getgid())  # resolved gid == os.getgid()
        st = os.stat(path)
        assert st.st_gid == os.getgid()
    finally:
        t.close()


# -- wrong resulting mode / gid -> fail closed --------------------------


def test_wrong_resulting_mode_fails_closed(tmp_path, monkeypatch):
    # bind produces non-0660 mode; force chmod to no-op so verification sees a
    # WRONG mode and must fail closed.
    path = str(tmp_path / "badmode.sock")
    monkeypatch.setattr(os, "chmod", lambda *_: None)
    with pytest.raises(SocketPermissionError) as ei:
        UnixDatagramShadowTransport(path, tap_socket_group=_current_group())
    assert "socket mode != 0660" in str(ei.value)
    assert not os.path.exists(path)  # cleaned up


def test_wrong_resulting_gid_fails_closed(tmp_path, monkeypatch):
    # Resolve the tap group to a gid DIFFERENT from the socket's actual gid and
    # force chown to no-op => verification sees gid mismatch -> fail closed.
    gid_other = os.getgid() + 1_000_042
    _fake = {
        "gr_name": "tap",
        "gr_gid": gid_other,
        "gr_mem": [],
    }
    try:
        _entry = type("grp", (), _fake)()  # attribute-access object like struct_group
    except TypeError:  # pragma: no cover
        _entry = None
    monkeypatch.setattr(tr.grp, "getgrnam", lambda _n: _entry)
    monkeypatch.setattr(os, "chown", lambda *_: None)
    path = str(tmp_path / "badgid.sock")
    with pytest.raises(SocketPermissionError) as ei:
        UnixDatagramShadowTransport(path, tap_socket_group="tap")
    assert "socket gid != tap gid" in str(ei.value)
    assert not os.path.exists(path)


def test_fchown_failure_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "chown", lambda *_: (_ for _ in ()).throw(OSError(1, "denied")))
    path = str(tmp_path / "denied.sock")
    with pytest.raises(SocketPermissionError):
        UnixDatagramShadowTransport(path, tap_socket_group=_current_group())
    assert not os.path.exists(path)  # partial socket unwound


# -- stale / symlink / regular-file protection --------------------------


def test_symlink_stale_path_refused(tmp_path):
    target = tmp_path / "real.sock"
    link = tmp_path / "link.sock"
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(target))
    s.close()
    os.symlink(str(target), str(link))
    with pytest.raises(SocketPermissionError) as ei:
        UnixDatagramShadowTransport(str(link), tap_socket_group=_current_group())
    assert "STALE_SOCKET_UNSAFE" in str(ei.value)
    assert os.path.islink(str(link))  # refuser: symlink still present


def test_regular_file_stale_path_refused(tmp_path):
    f = tmp_path / "plain.sock"
    f.write_bytes(b"not a socket")
    with pytest.raises(SocketPermissionError) as ei:
        UnixDatagramShadowTransport(str(f), tap_socket_group=_current_group())
    assert "STALE_SOCKET_UNSAFE" in str(ei.value)
    assert f.read_bytes() == b"not a socket"  # not unlinked


def test_stale_socket_path_cleanly_replaced(tmp_path):
    # A genuine pre-existing Unix socket may be taken over safely.
    p1 = tmp_path / "stale.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(str(p1))
    s.close()  # leaves a stale socket inode
    t = UnixDatagramShadowTransport(str(p1), tap_socket_group=_current_group())
    try:
        _assert_tap_inode(str(p1), os.getgid())
    finally:
        t.close()


# -- restart durability ---------------------------------------------------


def test_restart_durability_rebind(tmp_path):
    # worker restart = close (unlink) then rebind; perms must be re-applied.
    path = str(tmp_path / "durable.sock")
    gname = _current_group()
    t1 = UnixDatagramShadowTransport(path, tap_socket_group=gname)
    _assert_tap_inode(path, os.getgid())
    t1.close()
    assert not os.path.exists(path)
    t2 = UnixDatagramShadowTransport(path, tap_socket_group=gname)
    _assert_tap_inode(path, os.getgid())  # durable across process lifecycle
    t2.close()


def test_restart_durability_subprocess(tmp_path):
    # Simulate a REAL worker restart in a separate process: bind&enforce in the
    # child, stat from the parent; then parent rebinds and re-verifies.
    path = str(tmp_path / "subproc.sock")
    gname = _current_group()
    code = (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "from agent.shadow_worker.transport import UnixDatagramShadowTransport\n"
        "t = UnixDatagramShadowTransport(%r, tap_socket_group=%r)\n"
        "import time; time.sleep(5)\n"
        "t.close()\n"
        % (os.getcwd(), path, gname)
    )
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        # wait (bounded) for the child to bind+enforce before asserting
        deadline = time.monotonic() + 10
        while not os.path.exists(path) and time.monotonic() < deadline:
            time.sleep(0.05)
        _assert_tap_inode(path, os.getgid())
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    # parent-side rebind (next worker start) proves durable perms on a fresh bind
    t = UnixDatagramShadowTransport(path, tap_socket_group=gname)
    try:
        _assert_tap_inode(path, os.getgid())
    finally:
        t.close()