"""Sandbox root + canonical path resolution (Sprint 1.3.5 §4/§27)."""

from __future__ import annotations

import os
import stat
from typing import Optional

from .exceptions import SandboxPathEscape

#: Forbidden absolute path prefixes — any resolution landing here is DENY.
FORBIDDEN_PREFIXES = (
    "/proc", "/sys", "/dev", "/run", "/etc", "/boot", "/root",
)

#: Production paths that must never be reachable even via a legit root.
PRODUCTION_PATHS = (
    "/home/hermes/.hermes/config.yaml",
    "/home/hermes/.hermes/state.db",
    "/home/hermes/.ssh",
    "/etc/systemd/system/hermes-gateway.service",
    "/home/hermes/.hermes/.env",
)

#: Canonical sandbox root (persistent, Hermes-owned).
DEFAULT_SANDBOX_ROOT = os.path.expanduser(
    "~/.hermes/sandbox/system-mutation")


class SandboxRoot:
    """Hermes-owned sandbox root (owner=hermes, mode=700)."""

    def __init__(self, root: Optional[str] = None) -> None:
        self.root = os.path.abspath(root or DEFAULT_SANDBOX_ROOT)

    def ensure(self) -> str:
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        for sub in (".snapshots", ".txn", ".locks", ".service"):
            os.makedirs(os.path.join(self.root, sub), mode=0o700, exist_ok=True)
        os.chmod(self.root, 0o700)
        return self.root

    def exists(self) -> bool:
        return os.path.isdir(self.root)

    @property
    def real(self) -> str:
        return os.path.realpath(self.root)

    def resolve(self, target: str) -> str:
        return resolve_sandbox_path(self.root, target)


def _reject(reason: str) -> None:
    raise SandboxPathEscape(reason)


def resolve_sandbox_path(sandbox_root: str, target: str) -> str:
    """Resolve ``target`` to a canonical path strictly inside sandbox.

    Checks (all must pass, else SandboxPathEscape):
      - absolute root required
      - null bytes
      - lexical normalization (no ``..`` escape)
      - absolute escape
      - symlink components / final symlink resolve inside root
      - forbidden prefixes (/proc /sys /dev /run /etc /boot /root)
      - production ~/.hermes paths
      - parent realpath inside root (for create-style targets)
    """
    if not target or not isinstance(target, str):
        _reject("empty target")
    if "\x00" in target:
        _reject("null byte in target")
    if not os.path.isabs(sandbox_root):
        _reject(f"sandbox root must be absolute: {sandbox_root!r}")
    root = os.path.abspath(sandbox_root)

    # lexical normalization
    normalized = os.path.normpath(target)
    if normalized.startswith("..") or "/.." in normalized:
        _reject(f"path escapes via '..': {target!r}")
    if os.path.isabs(normalized):
        # absolute path must still resolve inside the root
        candidate = normalized
    else:
        candidate = os.path.join(root, normalized)

    candidate = os.path.normpath(candidate)
    root_real = os.path.realpath(root)
    # realpath the deepest EXISTING ancestor so symlinks in parents count
    head = candidate
    tail_parts: list = []
    while head and not os.path.exists(head):
        head, tail = os.path.split(head)
        if tail:
            tail_parts.append(tail)
        if head == "/":
            break
    if os.path.exists(head):
        resolved_head = os.path.realpath(head)
        candidate_resolved = os.path.join(
            resolved_head, *reversed(tail_parts))
        candidate_resolved = os.path.normpath(candidate_resolved)
    else:
        candidate_resolved = candidate

    if candidate_resolved != root_real and \
            not candidate_resolved.startswith(root_real + os.sep):
        _reject(f"target resolves outside sandbox root: {target!r}")

    # forbidden prefixes on the RESOLVED path
    for prefix in FORBIDDEN_PREFIXES:
        if candidate_resolved == prefix or \
                candidate_resolved.startswith(prefix + os.sep):
            _reject(f"target hits forbidden prefix {prefix}: {target!r}")

    # production paths (exact or under)
    for prod in PRODUCTION_PATHS:
        prod_real = os.path.realpath(prod)
        if candidate_resolved == prod_real or \
                candidate_resolved.startswith(prod_real + os.sep):
            _reject(f"target hits production path {prod}: {target!r}")

    # symlink check on the final component if it exists
    if os.path.islink(candidate):
        link_dest = os.path.realpath(candidate)
        if link_dest != root_real and \
                not link_dest.startswith(root_real + os.sep):
            _reject(f"target is a symlink escaping the sandbox: {target!r}")

    return candidate_resolved


def ensure_file_owner_hermes(path: str) -> None:
    """owner must be the current user (hermes in production)."""
    st = os.stat(path)
    if st.st_uid != os.getuid():
        _reject(f"file {path} is not owned by the sandbox user")


def sandbox_health_ok(sandbox_root: str) -> bool:
    return os.path.isdir(sandbox_root) and os.access(sandbox_root, os.W_OK)


def check_free_disk(sandbox_root: str, min_bytes: int = 1024 * 1024) -> bool:
    try:
        st = os.statvfs(sandbox_root)
        free = st.f_bavail * st.f_frsize
        return free >= min_bytes
    except OSError:
        return False
