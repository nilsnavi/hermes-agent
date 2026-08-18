"""Sandbox test service (Sprint 1.3.5 §16) — subprocess test daemon.

A sandbox-prefixed artificial test service. Production units
(hermes-gateway.service in particular) are BLOCKED by identity check.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import secrets
from typing import Optional

from .exceptions import SandboxServiceError

#: Only sandbox-prefixed service names are controllable.
SANDBOX_SERVICE_PREFIX = "hermes-sandbox"

#: Production services — always BLOCK.
BLOCKED_SERVICES = ("hermes-gateway", "hermes-gateway.service")

#: Minimal test daemon — lives entirely inside the sandbox.
_DAEMON_SOURCE = r'''
import json, os, signal, sys, time

state_path = sys.argv[1]
nonce = sys.argv[2]
spawn_child = sys.argv[3] == "1"
pid = os.getpid()
process_start = open(f"/proc/{pid}/stat").read().split()[21]
child = None
if spawn_child:
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
os.makedirs(os.path.dirname(state_path), exist_ok=True)

def write_state(extra=None):
    st = {"pid": pid, "owned": True, "running": True,
          "nonce": nonce, "process_start": process_start,
          "pgid": os.getpgrp(), "child_pid": child.pid if child else None}
    if extra:
        st.update(extra)
    with open(state_path, "w") as fh:
        json.dump(st, fh)

write_state({"started_at": time.time()})

def _stop(signum, frame):
    # write the terminal state, then hard-exit (os._exit: no further
    # Python signal handling, guaranteed termination)
    try:
        write_state({"running": False})
    except Exception:
        pass
    os._exit(0)

def _reload(signum, frame):
    # reload: re-write state (fresh started_at), keep the SAME PID
    try:
        write_state({"reloaded_at": time.time()})
    except Exception:
        pass

signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGHUP, _reload)  # reload keeps the PID

while True:
    time.sleep(0.2)
'''


def assert_sandbox_service_identity(service_name: str) -> None:
    """§16 — service identity guard. Production services: BLOCK."""
    if service_name in BLOCKED_SERVICES:
        raise SandboxServiceError(
            f"production service {service_name} is not controllable "
            f"via the sandbox runtime")
    if not service_name.startswith(SANDBOX_SERVICE_PREFIX):
        raise SandboxServiceError(
            f"service {service_name!r} is not a sandbox service "
            f"(prefix {SANDBOX_SERVICE_PREFIX!r} required)")


class SandboxTestService:
    """Subprocess test daemon bound to the sandbox root."""

    def __init__(self, sandbox_root, name: str = "hermes-sandbox-test") -> None:
        assert_sandbox_service_identity(name)
        self.name = name
        self._root = sandbox_root
        self._svc_dir = os.path.join(sandbox_root.root, ".service")
        os.makedirs(self._svc_dir, mode=0o700, exist_ok=True)
        self._state_path = os.path.join(self._svc_dir, "state.json")
        self._owner_path = os.path.join(self._svc_dir, "owner.json")
        self._proc: Optional[subprocess.Popen] = None

    @staticmethod
    def _process_start(pid: int) -> Optional[str]:
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as fh:
                return fh.read().split()[21]
        except (OSError, IndexError):
            return None

    def _assert_owned(self, state: dict) -> int:
        try:
            with open(self._owner_path, "r", encoding="utf-8") as fh:
                owner = json.load(fh)
            pid = int(state["pid"])
            valid = (
                state.get("owned") is True and
                state.get("nonce") == owner.get("nonce") and
                state.get("process_start") == self._process_start(pid) and
                int(state.get("pgid")) == os.getpgid(pid) and
                owner.get("name") == self.name
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            valid = False
            pid = 0
        if not valid:
            raise SandboxServiceError("sandbox service process identity is ambiguous")
        return pid

    def _state(self) -> dict:
        if not os.path.exists(self._state_path):
            return {}
        # the daemon writes state.json atomically-ish; tolerate a
        # mid-write read with a short bounded retry (JSONDecodeError
        # on an empty/partial file is a race, not a failure)
        for _ in range(20):
            try:
                with open(self._state_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except json.JSONDecodeError:
                time.sleep(0.01)
        return {}

    def start(self, *, spawn_child: bool = False) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return  # already running
        nonce = secrets.token_hex(16)
        with open(self._owner_path, "w", encoding="utf-8") as fh:
            json.dump({"nonce": nonce, "name": self.name}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.unlink(self._state_path)
        except OSError:
            pass
        self._proc = subprocess.Popen(
            [sys.executable, "-c", _DAEMON_SOURCE, self._state_path,
             nonce, "1" if spawn_child else "0"],
            cwd=self._root.root,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # wait for the state file (bounded)
        for _ in range(50):
            st = self._state()
            if st.get("pid") == self._proc.pid:
                return
            time.sleep(0.02)
        raise SandboxServiceError("service did not become ready")

    def stop(self) -> None:
        state = self._state()
        # Never signal a PID/process-group until the durable identity tuple
        # (name, nonce, PID start time, PGID) has been proven.  This prevents
        # PID reuse and forged state files from targeting unrelated processes.
        if not state.get("pid"):
            raise SandboxServiceError(
                "service identity evidence is missing; refusing to signal")
        owned_pid = self._assert_owned(state)
        owned_pgid = int(state["pgid"])
        child_pid = state.get("child_pid")
        if self._proc is None or self._proc.poll() is not None:
            # maybe running from a previous handle → check state file
            st = self._state()
            pid = st.get("pid")
            if not pid:
                raise SandboxServiceError("service is not running")
            try:
                os.killpg(owned_pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            # bounded wait for actual termination (no lingering daemons)
            for _ in range(50):
                if not os.path.exists(f"/proc/{pid}"):
                    break
                time.sleep(0.02)
            self._cleanup_state()
            return
        try:
            os.killpg(owned_pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(owned_pgid, signal.SIGKILL)
            self._proc.wait(timeout=5)
        # A forked child must not outlive the sandbox service.  Give init a
        # bounded opportunity to reap it, then hard-kill the proven group.
        if child_pid:
            for _ in range(50):
                if not os.path.exists(f"/proc/{int(child_pid)}"):
                    break
                time.sleep(0.01)
            if os.path.exists(f"/proc/{int(child_pid)}"):
                try:
                    os.killpg(owned_pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self._cleanup_state()

    def restart(self) -> None:
        try:
            self.stop()
        except SandboxServiceError:
            pass
        self.start()

    def reload(self) -> None:
        # reload = SIGHUP; daemon keeps the same PID
        pid = self.pid()
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError as exc:
            raise SandboxServiceError("service is not running") from exc

    def pid(self) -> int:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc.pid
        st = self._state()
        pid = st.get("pid")
        if not pid:
            raise SandboxServiceError("service is not running")
        return int(pid)

    def is_running(self) -> bool:
        try:
            pid = self.pid()
            return os.path.exists(f"/proc/{pid}")
        except SandboxServiceError:
            return False

    def health_probe(self) -> bool:
        st = self._state()
        return bool(st.get("pid")) and st.get("running") is True and \
            self.is_running()

    def _cleanup_state(self) -> None:
        try:
            os.unlink(self._state_path)
        except OSError:
            pass
