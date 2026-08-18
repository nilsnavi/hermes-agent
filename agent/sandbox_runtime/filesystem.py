"""Sandbox filesystem primitives — atomic write (Sprint 1.3.5 §15)."""

from __future__ import annotations

import os
import tempfile


def atomic_write(path: str, data: bytes, mode: int = 0o600) -> None:
    """Atomic file write: temp in same fs → fsync → chmod → rename →
    fsync parent dir. Original remains intact on crash before rename.

    The parent directory must already exist — creating it is the
    caller's (adapter's) responsibility so a missing parent surfaces
    as an OSError instead of a silent directory side effect.
    """
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".sandbox-write-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
        # fsync parent dir so the rename is durable
        try:
            dir_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
