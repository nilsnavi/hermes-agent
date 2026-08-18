"""Sandbox mutation adapters (Sprint 1.3.5 §5/§23).

Real filesystem/service mutations — invoked ONLY by the pipeline after
every gate. Fault injection points are deterministic and available
exclusively for tests/sandbox (never in production runtime).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .exceptions import (
    AdapterAfterBlock,
    SandboxError,
    UnknownExecutionResult,
)
from .filesystem import atomic_write
from .models import SandboxMutationRequest
from .root import resolve_sandbox_path
from .service import SandboxTestService


@dataclass
class AdapterResult:
    status: str  # SUCCESS / FAILED / UNKNOWN
    output: Dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    error: str = ""


class FaultInjector:
    """Deterministic fault injection — tests/sandbox only."""

    def __init__(self) -> None:
        self._armed: set = set()

    def arm(self, point: str) -> None:
        self._armed.add(point)

    def disarm(self, point: str) -> None:
        self._armed.discard(point)

    def check(self, point: str) -> None:
        if point in self._armed:
            from .exceptions import SandboxError
            raise SandboxError(f"fault injected at {point}")

    def armed_points(self) -> set:
        return set(self._armed)


class SandboxAdapter:
    """The ONLY sanctioned way to mutate sandbox resources.

    The pipeline hands this adapter a fully-validated operation; any
    direct call without pipeline gates is a contract violation. The
    adapter itself re-validates the path (defense in depth) and
    counts every invocation for the adapter_calls invariant.
    """

    def __init__(self, sandbox_root, telemetry=None) -> None:
        self._root = sandbox_root
        self._telemetry = telemetry
        self.adapter_calls = 0

    def execute(self, req: SandboxMutationRequest) -> AdapterResult:
        self.adapter_calls += 1
        if self._telemetry is not None:
            self._telemetry.inc("sandbox_mutation_attempts")
        try:
            resolved = resolve_sandbox_path(self._root.root, req.target)
        except Exception as exc:
            raise AdapterAfterBlock(
                f"adapter invoked with escaping target: {exc}") from exc

        op = req.operation
        args = req.arguments or {}

        if op in ("CREATE_FILE", "WRITE_FILE", "REPLACE_FILE",
                  "WRITE_TEST_CONFIG"):
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            atomic_write(resolved, _content(args),
                         mode=int(args.get("mode", 0o600)))
            return AdapterResult("SUCCESS", {"path": resolved})
        if op == "DELETE_FILE":
            if os.path.isdir(resolved) and not os.path.islink(resolved):
                return AdapterResult("FAILED", error_code="IS_DIRECTORY")
            os.remove(resolved)
            return AdapterResult("SUCCESS", {"path": resolved})
        if op == "RENAME_FILE":
            dest = args.get("to") or args.get("destination")
            if not dest:
                return AdapterResult("FAILED", error_code="NO_DESTINATION")
            dest_resolved = resolve_sandbox_path(self._root.root, dest)
            os.rename(resolved, dest_resolved)
            return AdapterResult("SUCCESS",
                                 {"from": resolved, "to": dest_resolved})
        if op == "CREATE_DIRECTORY":
            os.makedirs(resolved, exist_ok=True)
            return AdapterResult("SUCCESS", {"path": resolved})
        if op == "DELETE_EMPTY_DIRECTORY":
            os.rmdir(resolved)
            return AdapterResult("SUCCESS", {"path": resolved})
        if op == "CHMOD":
            mode = int(args.get("mode", 0o600))
            os.chmod(resolved, mode)
            return AdapterResult("SUCCESS", {"path": resolved, "mode": mode})
        if op in ("START_SANDBOX_SERVICE", "STOP_SANDBOX_SERVICE",
                  "RESTART_SANDBOX_SERVICE", "RELOAD_SANDBOX_SERVICE"):
            svc = SandboxTestService(self._root,
                                     name=req.target)
            action = op.replace("_SANDBOX_SERVICE", "").lower()
            getattr(svc, action)()
            return AdapterResult("SUCCESS",
                                 {"service": req.target, "action": action})
        # UNKNOWN operation → the pipeline gates it earlier; reaching
        # here is an invariant violation.
        from .transaction import assert_known_operation
        assert_known_operation(op)  # raises UnknownOperation
        raise UnknownExecutionResult(f"unclassified result for {op}")


def _content(args: Dict[str, Any]) -> bytes:
    content = args.get("content", "")
    if isinstance(content, str):
        return content.encode("utf-8")
    return bytes(content)
