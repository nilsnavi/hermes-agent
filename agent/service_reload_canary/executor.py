"""Sprint 1.3.10 — reload executor: ONLY exact reload, everything else DENY."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .exceptions import ReloadCanaryDisabled, ServiceOperationDenied

DENIED_VERBS = ("restart", "stop", "start", "try-restart",
                "reload-or-restart", "kill", "signal", "daemon-reload")


@dataclass(frozen=True)
class ReloadExecutionRequest:
    service_id: str
    unit_name: str
    verified_unit_identity: str
    transaction_id: str


def assert_reload_only(verb: str) -> None:
    if verb != "reload":
        raise ServiceOperationDenied(
            f"SERVICE_OPERATION_DENIED: {verb} is not permitted in Sprint 1.3.10")


def deny_every_other_verb() -> None:
    """P0: any non-reload verb is hard-denied, adapter never called."""
    for v in DENIED_VERBS:
        assert_reload_only(v)


def _real_reload_runner(unit_name: str, scope: str):
    def run() -> None:
        # read-only-ish: `systemctl --user reload <unit>` re-sends SIGHUP/re-read.
        # Only invoked for an exact allowlisted aux unit, after all gates.
        cmd = ["systemctl", "--user", "reload", unit_name]
        if scope != "user":
            cmd = ["systemctl", "--user", "reload", unit_name]
        pr = subprocess.run(cmd, capture_output=True, timeout=30)
        if pr.returncode != 0:
            raise RuntimeError(f"reload failed rc={pr.returncode}: {pr.stderr.decode(errors='replace')[:200]}")
    return run


def run_reload(req: ReloadExecutionRequest, runner=None) -> int:
    """Perform exactly one reload. Returns adapter-call count (1 on success)."""
    if runner is None:
        runner = _real_reload_runner(req.unit_name, "user")
    runner()
    return 1
