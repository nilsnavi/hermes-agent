"""Sprint 1.3.7 §13/§14 — preflight evidence + verified snapshot before mutation."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from .schema import validate_content_bytes


@dataclass(frozen=True)
class TargetEvidence:
    realpath: str
    parent_realpath: str
    islink: bool
    exists: bool
    uid: int | None = None
    owner: str | None = None
    mode: int | None = None
    inode: int | None = None
    dev: int | None = None
    size: int | None = None
    mtime_ns: int | None = None
    before_sha256: str | None = None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resource_fingerprint(realpath: str) -> str:
    return hashlib.sha256(realpath.encode("utf-8")).hexdigest()


def gather(target: str) -> TargetEvidence:
    realpath = os.path.realpath(target)
    parent = os.path.dirname(target)
    exists = os.path.lexists(target)
    islink = os.path.islink(target)
    ev = TargetEvidence(realpath=realpath, parent_realpath=os.path.realpath(parent),
                        islink=islink, exists=exists)
    if exists and not islink and os.path.isfile(target):
        st = os.stat(target)
        with open(target, "rb") as f:
            data = f.read()
        ev = TargetEvidence(
            realpath=realpath, parent_realpath=os.path.realpath(parent),
            islink=False, exists=True, uid=st.st_uid, owner=_uid_to_name(st.st_uid),
            mode=st.st_mode & 0o7777, inode=st.st_ino, dev=st.st_dev,
            size=st.st_size, mtime_ns=st.st_mtime_ns, before_sha256=sha256_bytes(data))
    return ev


def _uid_to_name(uid: int) -> str:
    import getpass
    import pwd
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


class SnapshotManager:
    """Verified per-transaction snapshot (before-state + auth binding)."""

    def __init__(self, store_dir: str) -> None:
        self._dir = store_dir

    def create(self, txid: str, target: str, ev: TargetEvidence,
               old_content: bytes | None) -> dict:
        os.makedirs(self._dir, exist_ok=True)
        snap = {
            "transaction_id": txid,
            "target": target,
            "target_fingerprint": resource_fingerprint(ev.realpath),
            "before_hash": ev.before_sha256,
            "before_bytes_b64": _b64(old_content) if old_content is not None else None,
            "mode": ev.mode,
            "owner": ev.owner,
            "mtime_ns": ev.mtime_ns,
            "schema_version": 1,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        snap["auth_binding"] = hashlib.sha256(
            (txid + "|" + snap["target_fingerprint"] + "|" + str(snap["before_hash"])).encode()
        ).hexdigest()
        path = os.path.join(self._dir, f"{txid}.snapshot.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f)
        return snap

    def load(self, txid: str) -> dict:
        with open(os.path.join(self._dir, f"{txid}.snapshot.json"), "r", encoding="utf-8") as f:
            return json.load(f)


def _b64(b: bytes | None) -> str | None:
    import base64
    return base64.b64encode(b).decode() if b is not None else None


def _unb64(s: str | None) -> bytes | None:
    import base64
    return base64.b64decode(s) if s is not None else None


def validate_before(target: str, ev: TargetEvidence, *, expected_owner: str,
                    allow_missing: bool = True) -> list[str]:
    """Fail-closed preflight consistency checks for the target."""
    errors: list[str] = []
    if ev.islink:
        errors.append("target must not be symlink")
    if ev.realpath != target:
        errors.append("target realpath mismatch (symlink)")
    if ev.exists:
        if not ev.before_sha256 or not ev.before_sha256:
            errors.append("missing before hash")
        if ev.owner != expected_owner:
            errors.append("target owner mismatch")
    elif not allow_missing:
        errors.append("target missing but not allowed")
    return errors


def validate_snapshot_match(snap: dict, ev: TargetEvidence) -> list[str]:
    errors: list[str] = []
    if snap.get("target_fingerprint") != resource_fingerprint(ev.realpath):
        errors.append("snapshot target fingerprint mismatch")
    if snap.get("before_hash") != ev.before_sha256:
        errors.append("snapshot before-hash vs current mismatch (drift)")
    return errors
