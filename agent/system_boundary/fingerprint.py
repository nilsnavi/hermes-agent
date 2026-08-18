"""Resource fingerprints (Sprint 1.3.3 §20).

Preflight fingerprint: realpath / device / inode / mode / uid / gid /
mtime_ns / size / resource_class. Fields may be optional; a missing
target yields None fields — values are never invented.
"""

import os
from dataclasses import dataclass
from typing import Optional

from .models import ResourceClass


@dataclass(frozen=True)
class ResourceFingerprint:
    realpath: Optional[str] = None
    device: Optional[int] = None
    inode: Optional[int] = None
    mode: Optional[int] = None
    uid: Optional[int] = None
    gid: Optional[int] = None
    mtime_ns: Optional[int] = None
    size: Optional[int] = None
    resource_class: Optional[str] = None
    is_symlink: bool = False
    exists: bool = False

    def to_dict(self) -> dict:
        return {
            "realpath": self.realpath,
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
            "mtime_ns": self.mtime_ns,
            "size": self.size,
            "resource_class": self.resource_class,
            "is_symlink": self.is_symlink,
            "exists": self.exists,
        }

    def stable_identity(self) -> Optional[tuple]:
        """The (device, inode) identity — None when unknown."""
        if self.device is None or self.inode is None:
            return None
        return (self.device, self.inode)

    def same_file(self, other: "ResourceFingerprint") -> bool:
        """Identity-level comparison — symlink swaps change identity."""
        a, b = self.stable_identity(), other.stable_identity()
        if a is not None and b is not None:
            return a == b
        # fall back to full comparison when identity unavailable
        return self == other


def fingerprint_path(path: str) -> ResourceFingerprint:
    """Fingerprint one path (following symlinks to the target).

    Missing files → all identity fields None (never invented).
    """
    realpath = None
    try:
        realpath = os.path.realpath(path)
    except OSError:
        pass

    try:
        st = os.stat(path)  # follows symlinks
    except OSError:
        return ResourceFingerprint(realpath=None, exists=False)

    is_symlink = os.path.islink(path)
    return ResourceFingerprint(
        realpath=realpath,
        device=st.st_dev,
        inode=st.st_ino,
        mode=st.st_mode,
        uid=st.st_uid,
        gid=st.st_gid,
        mtime_ns=st.st_mtime_ns,
        size=st.st_size,
        resource_class=None,
        is_symlink=is_symlink,
        exists=True,
    )


def fingerprint_changed(a: ResourceFingerprint,
                        b: ResourceFingerprint) -> bool:
    """True when the identity or content identity changed.

    Identity (dev, inode) change → changed (symlink swap / replace).
    Otherwise compare mtime_ns + size + mode.
    """
    if a.exists != b.exists:
        return True
    if not a.exists:
        return False  # both missing
    ia, ib = a.stable_identity(), b.stable_identity()
    if ia is not None and ib is not None and ia != ib:
        return True
    return (a.mtime_ns != b.mtime_ns) or (a.size != b.size) \
        or (a.mode != b.mode) or (a.is_symlink != b.is_symlink)


__all__ = [
    "ResourceFingerprint",
    "fingerprint_path",
    "fingerprint_changed",
]
