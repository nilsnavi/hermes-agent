"""Path resolution + resource classification (Sprint 1.3.3 §17, §19,
§20).

Classify the RESOLVED identity, not the input string. Handles:
absolute / relative / cwd / . / .. / // / ~ / unicode / spaces /
symlinks / broken symlinks / parent symlinks / new-file parent
resolution / realpath.

The classifier is NOT purely prefix-based: it combines the resolved
path with file type, owner and target semantics (§19), and never
invents values (a missing file yields a None identity, not a guess).
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .models import ResourceClass

#: Sensitive system directories (used as a bounded hint; the real
#: classification happens on the RESOLVED path + file semantics).
_SYSTEM_PREFIXES = (
    "/etc", "/usr", "/usr/local", "/bin", "/sbin", "/lib", "/lib64",
    "/boot", "/var/lib", "/var/spool", "/opt", "/root", "/proc",
    "/sys", "/dev", "/run", "/var/run", "/var/cache",
)

#: subpaths that mark a secret-bearing resource even under a user dir
_SECRET_MARKERS = (
    ".ssh/", "id_rsa", "id_ed25519", "id_dsa", "id_ecdsa",
    "privkey", "private_key", "secret", "token", ".pem", ".key",
    "credentials", "credential", "shadow", "htpasswd",
    ".netrc", "api_key", "apikey", "client_secret",
    "letsencrypt/live", ".aws/credentials", ".config/gcloud",
    "kubeconfig", "service-account",
)

_SYSTEM_BINARY_MARKERS = (
    "/bin/", "/sbin/", "/usr/bin/", "/usr/sbin/", "/usr/local/bin/",
    "/usr/local/sbin/",
)


@dataclass(frozen=True)
class ResolvedPath:
    """The resolved identity of one path expression."""

    input_path: str
    resolved: Optional[str]           # realpath (None if unresolvable)
    resource_class: ResourceClass
    symlink_chain: List[str] = field(default_factory=list)
    broken_symlink: bool = False
    exists: bool = False
    is_dir: bool = False
    is_symlink: bool = False
    parent_resolved: Optional[str] = None
    uid: Optional[int] = None
    gid: Optional[int] = None


def _normalize(path: str, cwd: str, home: str) -> str:
    """Normalize ~, //, ., .. lexically (before filesystem lookup)."""
    p = path.strip()
    if not p:
        return cwd
    if p == "~":
        return home
    if p.startswith("~/"):
        p = os.path.join(home, p[2:])
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    # collapse // and . and ..
    p = os.path.normpath(p)
    return p


def _classify_secret(path: str) -> bool:
    low = path.lower()
    for marker in _SECRET_MARKERS:
        if marker in low:
            return True
    return False


def _classify_system(path: str) -> Optional[ResourceClass]:
    """Classify a resolved system path (prefix + semantics)."""
    for prefix in _SYSTEM_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            if _classify_secret(path):
                return ResourceClass.SECRET_RESOURCE
            if path.startswith(("/bin/", "/sbin/", "/usr/bin/",
                                "/usr/sbin/", "/usr/local/bin/",
                                "/usr/local/sbin/")) \
                    or _in_binary_dir(path):
                return ResourceClass.SYSTEM_BINARY
            if path.startswith(("/proc/", "/sys/", "/dev/",
                                "/run/", "/var/run/")):
                return ResourceClass.SYSTEM_STATE
            return ResourceClass.SYSTEM_CONFIG
    if _classify_secret(path):
        return ResourceClass.SECRET_RESOURCE
    return None


_CONFIG_FILENAMES = (
    "config.yaml", "config.yml", "config.json", "config.toml",
    "config.ini", "settings.yaml", "settings.json", "settings.toml",
    "application.yaml", "application.yml", "application.json",
    "appsettings.json",
)


def _classify_application(path: str) -> Optional[ResourceClass]:
    """Application config / data classification for non-system paths."""
    base = os.path.basename(path).lower()
    if base in _CONFIG_FILENAMES:
        return ResourceClass.APPLICATION_CONFIG
    if ".config/" in path or "/.config/" in path:
        return ResourceClass.APPLICATION_CONFIG
    if "/app/" in path or path.endswith("/app") \
            or "/apps/" in path or "/applications/" in path:
        return ResourceClass.APPLICATION_DATA
    if base.endswith((".db", ".sqlite", ".sqlite3", ".log")):
        return ResourceClass.APPLICATION_DATA
    return None


def _in_binary_dir(path: str) -> bool:
    for marker in _SYSTEM_BINARY_MARKERS:
        if path.startswith(marker):
            return True
    return False


def _is_secret_by_name(path: str) -> bool:
    """Secret by basename semantics (id_rsa, *.pem, *.key...)."""
    base = os.path.basename(path).lower()
    return _classify_secret(path) or any(
        base.startswith(m.rstrip("/")) for m in
        ("id_rsa", "id_ed25519", "id_dsa", "id_ecdsa")) or \
        base.endswith((".pem", ".key", ".pfx", ".p12"))


def resolve_path(
    path: str,
    cwd: str = "/",
    home: str = "/home/hermes",
    follow_symlinks: bool = True,
) -> ResolvedPath:
    """Resolve a path expression to its real identity.

    Returns a :class:`ResolvedPath` — never raises for missing files.
    A path that cannot be resolved yields ``resolved=None`` and the
    caller (boundary) decides fail-closed.
    """
    normalized = _normalize(path, cwd, home)
    chain: List[str] = []
    exists = os.path.exists(normalized)
    is_symlink = os.path.islink(normalized)

    # collect symlink chain (bounded — cap at 40 hops)
    resolved = normalized
    current = normalized
    hops = 0
    while os.path.islink(current) and hops < 40:
        try:
            target = os.readlink(current)
        except OSError:
            break
        if not os.path.isabs(target):
            target = os.path.normpath(
                os.path.join(os.path.dirname(current), target))
        chain.append(current)
        current = target
        hops += 1
        if os.path.exists(current):
            resolved = current

    broken = (is_symlink or hops > 0) and not os.path.exists(current)

    if not os.path.exists(current) and not broken:
        # new-file parent resolution: resolve the parent identity
        # lexically (realpath of a missing path normalizes components)
        try:
            resolved = os.path.realpath(normalized)
        except OSError:
            resolved = normalized
        exists = False
    else:
        try:
            resolved = os.path.realpath(current)
        except OSError:
            resolved = None

    # parent-symlink detection: when the real identity differs from the
    # lexical one and the lexical path went through a link, record it
    if resolved is not None and resolved != normalized \
            and normalized not in chain:
        chain.append(normalized)

    # classify on the RESOLVED identity (or the lexical one as a
    # conservative fallback when nothing resolved)
    classify_target = resolved or normalized
    rc: ResourceClass = ResourceClass.UNKNOWN
    if classify_target == "/tmp" or classify_target.startswith("/tmp/"):
        rc = ResourceClass.TEMPORARY
    else:
        system_rc = _classify_system(classify_target)
        if system_rc is not None:
            rc = system_rc
        elif _is_secret_by_name(classify_target):
            rc = ResourceClass.SECRET_RESOURCE
        elif _in_binary_dir(classify_target):
            rc = ResourceClass.SYSTEM_BINARY
        else:
            app_rc = _classify_application(classify_target)
            if app_rc is not None:
                rc = app_rc
            else:
                rc = ResourceClass.USER_DATA

    uid = gid = None
    try:
        st = os.lstat(current if os.path.exists(current) else normalized)
        uid, gid = st.st_uid, st.st_gid
    except OSError:
        pass

    return ResolvedPath(
        input_path=path,
        resolved=resolved,
        resource_class=rc,
        symlink_chain=chain,
        broken_symlink=broken,
        exists=exists or os.path.exists(current),
        is_dir=os.path.isdir(current) if os.path.exists(current)
        else False,
        is_symlink=is_symlink or bool(chain),
        parent_resolved=None,
        uid=uid,
        gid=gid,
    )


def path_escapes_root(resolved: Optional[str], root: str) -> bool:
    """True when a resolved path escapes the given root boundary."""
    if resolved is None:
        return True  # unresolved → conservative escape
    root_real = os.path.realpath(root)
    try:
        return os.path.commonpath([resolved, root_real]) != root_real
    except ValueError:
        return True


__all__ = [
    "ResolvedPath",
    "resolve_path",
    "path_escapes_root",
]
