"""Sprint 1.3.9 — FakeServiceAdapter: simulated read-only states for tests/chaos.

NO production mutation: the fake never touches real systemd/processes.
"""
from __future__ import annotations


def make_state(*, unit_name="x.service", executable="/usr/local/bin/x",
               pid=1000, health="healthy", active=True) -> dict:
    return {"unit_name": unit_name, "executable": executable, "MainPID": pid,
            "active": active, "health": health}


def state_for(profile, *, running=True, exec_ok=True, health="healthy") -> dict:
    return make_state(unit_name=profile.unit_name,
                      executable=profile.expected_executable if exec_ok else "/elsewhere/bin/x",
                      pid=1000 + abs(hash(profile.service_id)) % 1000,
                      health=health, active=running)


def raw_identity_hint(state) -> dict:
    """Expose just the identity-relevant raw fields (like systemctl Show)."""
    return {"unit_name": state.get("unit_name"), "executable": state.get("executable"),
            "MainPID": state.get("MainPID"), "active": state.get("active")}
