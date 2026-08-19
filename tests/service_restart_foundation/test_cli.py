"""Sprint 1.3.12 — read-only CLI (status/inspect/eligibility/transition-plan/
quiescence-plan/recovery-plan). No execute verb exists.
"""
from __future__ import annotations

import subprocess
import sys


def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "agent.service_restart_foundation.cli", *args],
        capture_output=True, text=True, cwd="/home/hermes/.hermes/hermes-agent-sprint137",
    )


class TestCliReadOnly:
    def test_status_command(self):
        r = _cli("status")
        assert r.returncode == 0, r.stderr
        assert "hermes-aux-canary" in r.stdout.lower() or "restart" in r.stdout.lower()

    def test_inspect_aux(self):
        r = _cli("inspect", "hermes-aux-canary")
        assert r.returncode == 0, r.stderr

    def test_eligibility_aux(self):
        r = _cli("eligibility", "hermes-aux-canary")
        assert r.returncode == 0, r.stderr

    def test_transition_plan(self):
        r = _cli("transition-plan", "hermes-aux-canary")
        assert r.returncode == 0, r.stderr

    def test_quiescence_plan(self):
        r = _cli("quiescence-plan", "hermes-aux-canary")
        assert r.returncode == 0, r.stderr

    def test_recovery_plan(self):
        r = _cli("recovery-plan", "hermes-aux-canary")
        assert r.returncode == 0, r.stderr

    def test_no_execute_verb(self):
        r = _cli("execute", "hermes-aux-canary")
        assert r.returncode != 0  # execute must not exist
        assert "no such" in r.stderr.lower() or "usage" in r.stderr.lower() or \
            "unknown" in r.stderr.lower() or "error" in r.stderr.lower()