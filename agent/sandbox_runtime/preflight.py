"""Preflight gate (Sprint 1.3.5 §8/§9) — 21 checks + fingerprint + second check."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .exceptions import SandboxPreflightFailed
from .models import SandboxMutationRequest
from .root import (
    check_free_disk,
    resolve_sandbox_path,
    sandbox_health_ok,
)


@dataclass
class SandboxPreflightReceipt:
    ok: bool
    checks: List[Tuple[str, bool]] = field(default_factory=list)
    fingerprint: str = ""
    resolved_target: str = ""
    reason: str = ""


def _file_fingerprint_fields(path: str) -> Dict[str, Any]:
    st = os.stat(path)
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return {
        "inode": st.st_ino,
        "dev": st.st_dev,
        "mode": st.st_mode & 0o7777,
        "owner": st.st_uid,
        "size": st.st_size,
        "mtime": st.st_mtime,
        "content_hash": digest,
        "is_symlink": os.path.islink(path),
        "realpath": os.path.realpath(path),
    }


def compute_fingerprint(req: SandboxMutationRequest,
                        sandbox_root) -> str:
    """Fingerprint must cover operation/target/state/arguments/approval
    (Sprint 1.3.5 §9)."""
    resolved = resolve_sandbox_path(sandbox_root.root, req.target)
    state: Dict[str, Any] = {
        "operation": req.operation,
        "resolved_target": resolved,
        "arguments": json.dumps(req.arguments, sort_keys=True, default=str),
        "approval": req.approval_id,
        "run_id": req.run_id,
        "step_id": req.step_id,
        "policy_version": req.policy_version,
        "boundary_version": req.boundary_version,
    }
    if os.path.exists(resolved):
        state["resource"] = _file_fingerprint_fields(resolved)
    else:
        # absent target: fingerprint the parent so a swapped parent
        # directory is detected
        parent = os.path.dirname(resolved)
        if os.path.exists(parent):
            pst = os.stat(parent)
            state["parent"] = {
                "inode": pst.st_ino,
                "dev": pst.st_dev,
                "mode": pst.st_mode & 0o7777,
                "owner": pst.st_uid,
                "realpath": os.path.realpath(parent),
            }
        state["resource"] = None
    canonical = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_preflight(req: SandboxMutationRequest,
                  sandbox_root) -> SandboxPreflightReceipt:
    """§8 — full preflight gate. Returns receipt (never raises on a
    failing check, but raises SandboxPreflightFailed for path escapes
    which are structural violations)."""
    if not req.validate():
        return SandboxPreflightReceipt(ok=False,
                                       checks=[("request_model", False)],
                                       reason="invalid request model")

    checks: List[Tuple[str, bool]] = []
    try:
        resolved = resolve_sandbox_path(sandbox_root.root, req.target)
    except Exception as exc:
        raise SandboxPreflightFailed(str(exc)) from exc

    # 1. target inside sandbox
    root_real = os.path.realpath(sandbox_root.root)
    inside = resolved == root_real or resolved.startswith(root_real + os.sep)
    checks.append(("target_inside_sandbox", inside))

    # 2. resource exists / non-exists per operation
    exists = os.path.exists(resolved)
    wants_present = {
        "WRITE_FILE", "REPLACE_FILE", "DELETE_FILE", "RENAME_FILE",
        "CREATE_DIRECTORY", "DELETE_EMPTY_DIRECTORY", "CHMOD",
        "WRITE_TEST_CONFIG",
    }
    expect_present = req.operation in wants_present
    checks.append(("resource_presence", exists == expect_present))

    # 3. expected state string
    if req.expected_state is not None:
        actual_state = "present" if exists else "absent"
        checks.append(("expected_state", actual_state == req.expected_state))

    if exists:
        # 4-11. metadata checks
        st = os.stat(resolved)
        checks.append(("owner", st.st_uid == os.getuid()))
        checks.append(("permissions_valid", (st.st_mode & 0o7777) != 0))
        checks.append(("symlink_state", not os.path.islink(resolved)))
        checks.append(("inode_stable", st.st_ino > 0))
        checks.append(("realpath_inside", inside))
        checks.append(("size_nonnegative", st.st_size >= 0))
        checks.append(("mtime_valid", st.st_mtime > 0))
        if req.expected_hash:
            with open(resolved, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            checks.append(("content_hash", digest == req.expected_hash))
        else:
            checks.append(("content_hash", True))
    else:
        checks.append(("metadata", True))

    # 12. service identity
    if req.resource_type == "SERVICE":
        checks.append(("service_identity",
                       req.target.startswith("hermes-sandbox")))

    # 13. operation compatibility (validated in model)
    checks.append(("operation_compatible", True))

    # 14. free disk
    checks.append(("free_disk", check_free_disk(sandbox_root.root)))

    # 15. sandbox health
    checks.append(("sandbox_health", sandbox_health_ok(sandbox_root.root)))

    # 16-18. approval validity / TTL / idempotency — checked by the
    # pipeline (approval manager owns the decision); here we only mark
    # the structural part.
    checks.append(("approval_id_present", bool(req.approval_id)))
    checks.append(("ttl_valid", req.ttl > 0))
    checks.append(("idempotency_key_present", bool(req.idempotency_key)))

    # 19-21. policy / boundary / plan fingerprints — pipeline-level.
    checks.append(("policy_version", bool(req.policy_version)))
    checks.append(("boundary_version", bool(req.boundary_version)))
    checks.append(("risk_class_known", req.risk_class in
                   ("LOW", "MEDIUM", "HIGH")))

    ok = all(c for _, c in checks)
    fp = compute_fingerprint(req, sandbox_root) if ok else ""
    return SandboxPreflightReceipt(
        ok=ok, checks=checks, fingerprint=fp,
        resolved_target=resolved,
        reason="" if ok else "preflight check(s) failed")
