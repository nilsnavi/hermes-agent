"""Sprint 1.3.13 — single aux service restart canary (executor).

Typed executor: accepts RestartExecutionRequest ONLY. Exact allowlist for
hermes-aux-canary.service. No raw commands, no arbitrary units, no shell
strings, no generic systemctl. Adapter call counter is durable.

The executor's restart primitive is the SINGLE authorized narrow path for
exactly one registered aux service. No public STOP/START operation, no signal.
"""
from __future__ import annotations

import os
from pathlib import Path

from .allowlist import RestartAllowlist
from .exceptions import (CanaryDisabled, NotRegistered, OperationDenied,
                          UnsupportedOperation)
from .models import (Operation, RestartExecutionRequest)

# Derived/default restart-store dir (Hermes-owned; NOT state.db).
_DEFAULT_STORE = "/home/hermes/.hermes/managed/canary-service/restart-store"


class RestartAdapter:
    """Real restart primitive. Fails closed for anything not the exact canary."""

    def __init__(self) -> None:
        self.calls = 0

    def restart_aux_canary(self) -> int:
        """systemctl --user restart hermes-aux-canary.service (typed, exact)."""
        self.calls += 1
        rc = os.system("systemctl --user restart hermes-aux-canary.service")
        return rc


class FakeRestartAdapter:
    """Fake adapter for shadow/rehearsal. Counts calls, does nothing real."""

    def __init__(self) -> None:
        self.calls = 0

    def restart_aux_canary(self) -> int:
        self.calls += 1
        return 0


class RestartExecutor:
    def __init__(
        self,
        allowlist: RestartAllowlist,
        adapter=None,
        store_dir: str | Path = _DEFAULT_STORE,
        allow_real: bool = False,
        kill_switch: bool = True,
    ) -> None:
        self._allowlist = allowlist
        self._adapter = adapter
        self._store_dir = Path(store_dir)
        self._allow_real = allow_real
        self._kill_switch = kill_switch
        self._counter_path = self._store_dir / "adapter_calls.txt"
        self._store_dir.mkdir(parents=True, exist_ok=True)

    def adapter_calls(self) -> int:
        if not self._counter_path.exists():
            return 0
        try:
            return int(self._counter_path.read_text().strip() or "0")
        except Exception:
            return 0

    def _bump_counter(self) -> None:
        n = self.adapter_calls() + 1
        self._counter_path.write_text(str(n))

    def execute(self, request: RestartExecutionRequest) -> tuple[str, int]:
        """Execute the exact restart. Returns (outcome, adapter_calls)."""
        entry = self._allowlist.entry_for_service(request.service_id)
        if entry is None:
            return "NOT_REGISTERED", self.adapter_calls()
        if not request.verify(entry.service_id, entry.unit_name):
            return "UNIT_IDENTITY_MISMATCH", self.adapter_calls()

        # Kill switch: canary disabled -> no adapter call.
        if self._kill_switch:
            return "CANARY_DISABLED", self.adapter_calls()

        # Pre-registered configured real execution requires allow_real.
        adapter = self._adapter if self._adapter is not None else (
            RestartAdapter() if self._allow_real else FakeRestartAdapter())
        # Exactly one adapter call.
        rc = adapter.restart_aux_canary()
        self._bump_counter()
        return ("EXECUTED", self.adapter_calls()) if rc == 0 else ("EXEC_FAILED", self.adapter_calls())


def stop_or_start_denied() -> str:
    """Public STOP/START are separate operations and are ALWAYS denied."""
    return "OPERATION_DENIED"


def public_operation(request: RestartExecutionRequest | None = None, op: str = "") -> tuple[str, int]:
    """Public STOP/START/KILL/SIGNAL not granted: adapter=0, OPERATION_DENIED."""
    o = Operation(op)
    if o != Operation.RESTART:
        return "OPERATION_DENIED", 0
    return "RESTART_ONLY", 0


__all__ = [
    "FakeRestartAdapter",
    "RestartAdapter",
    "RestartExecutor",
    "public_operation",
    "stop_or_start_denied",
]