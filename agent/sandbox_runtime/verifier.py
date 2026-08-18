"""Independent post-execution verification (Sprint 1.3.5 §19)."""

from __future__ import annotations

import hashlib
import os
from typing import Optional

from .exceptions import VerifyFailed
from .models import SandboxMutationRequest
from .root import resolve_sandbox_path


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def verify_mutation(req: SandboxMutationRequest, sandbox_root,
                    adapter_said_success: bool = True) -> None:
    """Independent verification — adapter result is NOT proof of state.

    Raises VerifyFailed on any discrepancy. A failed verification
    triggers rollback at the pipeline level.
    """
    resolved = resolve_sandbox_path(sandbox_root.root, req.target)
    op = req.operation
    exists = os.path.exists(resolved)
    is_symlink = os.path.islink(resolved)

    def _fail(reason: str) -> None:
        raise VerifyFailed(f"verification failed for {req.operation} "
                           f"{req.target}: {reason}")

    if op in ("CREATE_FILE", "WRITE_FILE", "REPLACE_FILE",
              "CREATE_DIRECTORY", "WRITE_TEST_CONFIG"):
        if not exists or is_symlink:
            _fail("target missing or symlink after create/write")
        st = os.stat(resolved)
        if st.st_uid != os.getuid():
            _fail("owner mismatch")
        if req.expected_hash:
            if _sha256(resolved) != req.expected_hash:
                _fail("content hash mismatch")
        args = req.arguments or {}
        if "size" in args and st.st_size != args["size"]:
            _fail(f"size mismatch: {st.st_size} != {args['size']}")
    elif op == "DELETE_FILE":
        if exists or is_symlink:
            _fail("target still present after delete")
    elif op == "RENAME_FILE":
        # source must be gone; destination present
        dest = req.arguments.get("to") or req.arguments.get("destination")
        if dest is None:
            _fail("rename without destination")
        dest_resolved = resolve_sandbox_path(sandbox_root.root, dest)
        if exists:
            _fail("source still present after rename")
        if not os.path.exists(dest_resolved):
            _fail("destination missing after rename")
    elif op == "CHMOD":
        mode = req.arguments.get("mode")
        if mode is None:
            _fail("chmod without mode")
        if not exists:
            _fail("target missing after chmod")
        actual = os.stat(resolved).st_mode & 0o7777
        if actual != int(mode):
            _fail(f"permission mismatch: {oct(actual)} != {oct(mode)}")
    elif op in ("DELETE_EMPTY_DIRECTORY",):
        if exists:
            _fail("directory still present after delete")
    else:
        # service operations verified by the service layer
        return
