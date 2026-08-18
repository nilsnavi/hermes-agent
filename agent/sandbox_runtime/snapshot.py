"""Snapshot / backup (Sprint 1.3.5 §11) — per-operation backup BEFORE mutation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
from dataclasses import dataclass, field
from typing import Dict, Optional

from .exceptions import BackupFailed
from .models import SandboxMutationRequest
from .root import resolve_sandbox_path


def _resource_fingerprint(path: str) -> str:
    return hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()


def _auth_payload(manifest: Dict) -> bytes:
    clean = {k: v for k, v in manifest.items() if k != "auth_tag"}
    return json.dumps(clean, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")


@dataclass
class Snapshot:
    txid: str
    dir: str
    manifest: Dict = field(default_factory=dict)
    target: str = ""

    @property
    def sha256sums(self) -> str:
        return os.path.join(self.dir, "SHA256SUMS")


class SnapshotManager:
    """Creates a per-operation backup under ``.snapshots/<txid>/``.

    Backup is created BEFORE mutation; if it fails → BACKUP_FAILED and
    the mutation must not proceed (Sprint 1.3.5 §11).
    """

    def __init__(self, sandbox_root) -> None:
        self._root = sandbox_root

    def _snap_dir(self, txid: str) -> str:
        base = os.path.join(self._root.root, ".snapshots")
        if not os.path.isdir(base):
            raise BackupFailed(f".snapshots is not a directory: {base}")
        return os.path.join(base, txid)

    def _auth_key(self, *, create: bool) -> bytes:
        base = os.path.join(self._root.root, ".snapshots")
        path = os.path.join(base, ".auth-key")
        if create and not os.path.exists(path):
            key = secrets.token_bytes(32)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    os.write(fd, key)
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except FileExistsError:
                pass
        with open(path, "rb") as fh:
            key = fh.read()
        if len(key) != 32:
            raise BackupFailed("snapshot authentication key is invalid")
        return key

    def create(self, txid: str, req: SandboxMutationRequest,
               resolved_target: str) -> Snapshot:
        snap_dir = self._snap_dir(txid)
        try:
            os.makedirs(snap_dir, mode=0o700, exist_ok=False)
        except FileExistsError as exc:
            raise BackupFailed(f"snapshot dir already exists: {snap_dir}") \
                from exc
        except OSError as exc:
            raise BackupFailed(f"cannot create snapshot dir: {exc}") from exc

        manifest: Dict = {
            "txid": txid,
            "transaction_id": txid,
            "request_id": req.request_id,
            "operation": req.operation,
            "target": resolved_target,
            "resource_fingerprint": _resource_fingerprint(resolved_target),
            "before_state": req.expected_state,
            "files": {},
        }
        sums_lines = []
        if os.path.exists(resolved_target):
            backed = os.path.join(snap_dir, "target.bin")
            try:
                shutil.copy2(resolved_target, backed)
            except OSError as exc:
                shutil.rmtree(snap_dir, ignore_errors=True)
                raise BackupFailed(f"cannot copy target: {exc}") from exc
            st = os.stat(resolved_target)
            with open(backed, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            manifest["files"]["target.bin"] = {
                "source": resolved_target,
                "sha256": digest,
                "mode": st.st_mode & 0o7777,
                "owner": st.st_uid,
                "size": st.st_size,
            }
            sums_lines.append(f"{digest}  target.bin")
            # permissions backup (restored on rollback)
            with open(os.path.join(snap_dir, "perms.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({
                    "mode": st.st_mode & 0o7777,
                    "owner": st.st_uid,
                    "group": st.st_gid,
                }, fh)
            sums_lines.append(
                f"{_file_digest(os.path.join(snap_dir, 'perms.json'))}  perms.json")
        else:
            manifest["files"] = {}
            manifest["absent"] = True

        try:
            manifest["auth_tag"] = hmac.new(
                self._auth_key(create=True), _auth_payload(manifest),
                hashlib.sha256).hexdigest()
        except OSError as exc:
            shutil.rmtree(snap_dir, ignore_errors=True)
            raise BackupFailed("cannot authenticate snapshot") from exc

        with open(os.path.join(snap_dir, "manifest.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, default=str)
        sums_lines.append(
            f"{_file_digest(os.path.join(snap_dir, 'manifest.json'))}  manifest.json")
        with open(os.path.join(snap_dir, "SHA256SUMS"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(sums_lines) + "\n")
        return Snapshot(txid=txid, dir=snap_dir, manifest=manifest,
                        target=resolved_target)

    def verify(self, snap: Snapshot) -> bool:
        """Verify SHA256SUMS of the snapshot (self-check)."""
        sums_path = snap.sha256sums
        if not os.path.exists(sums_path):
            return False
        try:
            with open(sums_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    digest, name = line.split("  ", 1)
                    path = os.path.join(snap.dir, name)
                    if not os.path.exists(path):
                        return False
                    if _file_digest(path) != digest:
                        return False
        except OSError:
            return False
        return True

    def validate_for(self, snap: Snapshot, transaction_id: str,
                     resolved_target: str) -> bool:
        """Authenticate a snapshot against its transaction and resource.

        All metadata is re-read from disk.  The in-memory manifest is never
        trusted on a recovery/rollback path.
        """
        try:
            manifest_path = os.path.join(snap.dir, "manifest.json")
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
            if not isinstance(manifest, dict):
                return False
            supplied_tag = manifest.get("auth_tag")
            expected_tag = hmac.new(self._auth_key(create=False),
                                    _auth_payload(manifest),
                                    hashlib.sha256).hexdigest()
            if not isinstance(supplied_tag, str) or not hmac.compare_digest(
                    supplied_tag, expected_tag):
                return False
            if manifest.get("transaction_id", manifest.get("txid")) != transaction_id:
                return False
            if snap.txid != transaction_id:
                return False
            if manifest.get("resource_fingerprint") != _resource_fingerprint(resolved_target):
                return False
            if os.path.realpath(manifest.get("target", "")) != os.path.realpath(resolved_target):
                return False
            if not self.verify(snap):
                return False
            files = manifest.get("files")
            if not isinstance(files, dict):
                return False
            if manifest.get("absent"):
                return not files and not os.path.exists(os.path.join(snap.dir, "target.bin"))
            entry = files.get("target.bin")
            if not isinstance(entry, dict):
                return False
            content = os.path.join(snap.dir, "target.bin")
            if not os.path.isfile(content) or _file_digest(content) != entry.get("sha256"):
                return False
            with open(os.path.join(snap.dir, "perms.json"), "r", encoding="utf-8") as fh:
                perms = json.load(fh)
            return (isinstance(perms, dict) and
                    isinstance(perms.get("mode"), int) and
                    isinstance(perms.get("owner"), int) and
                    isinstance(perms.get("group"), int))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    def restore(self, snap: Snapshot, resolved_target: str) -> None:
        """Restore the target from the snapshot (rollback path)."""
        target_abs = resolve_sandbox_path(self._root.root, resolved_target)
        if not self.validate_for(snap, snap.txid, target_abs):
            raise BackupFailed("snapshot authenticity validation failed")
        backed = os.path.join(snap.dir, "target.bin")
        if snap.manifest.get("absent") and not os.path.exists(backed):
            # snapshot captured ABSENT → restore means delete
            if os.path.exists(target_abs) or os.path.islink(target_abs):
                os.remove(target_abs)
            return
        if not os.path.exists(backed):
            raise BackupFailed(
                f"snapshot {snap.txid} is missing target.bin — "
                f"restore cannot proceed")
        os.makedirs(os.path.dirname(target_abs), exist_ok=True)
        shutil.copy2(backed, target_abs)
        # restore permissions from perms.json
        perms_path = os.path.join(snap.dir, "perms.json")
        if os.path.exists(perms_path):
            with open(perms_path, "r", encoding="utf-8") as fh:
                perms = json.load(fh)
            os.chmod(target_abs, perms.get("mode", 0o600))


def _file_digest(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()
