"""Sprint 1.3.9 — read-only service foundation CLI (no execute)."""
from __future__ import annotations

import sys

from .eligibility import evaluate
from .identity import verify_identity
from .registry import ServiceRegistry


def _modes():
    import os
    from .flags import foundation_enabled, get_mode
    return {"enabled": foundation_enabled(), "mode": get_mode().value, "system_control": "OFF"}


def main(argv=None) -> int:
    a = sys.argv[2] if len(sys.argv) > 2 else ""
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    r = ServiceRegistry()
    if cmd == "status":
        print(_modes())
        for sid, p in r.profiles.items():
            print(f"{sid}: class={p.service_class.value} crit={p.criticality.value} "
                  f"self={p.self_control_class.value} reload={p.reload_supported} restart={p.restart_supported}")
        return 0
    return 0
