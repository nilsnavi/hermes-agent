"""Sprint 1.3.8 §46 — read-only production-policy CLI (no generic execute)."""
from __future__ import annotations

import argparse
import sys


def _engine():
    from .policy import PolicyEngine
    return PolicyEngine()


def cmd_status(e):
    from . import flags
    print(f"enabled: {flags.get_enabled()}")
    print(f"mode: {flags.get_mode().value}")
    print(f"limited_active: {flags.limited_active()}")
    eng = e
    print(f"profiles: {len(eng.profiles)}")


def cmd_profiles(e):
    for pid, p in e.profiles.items():
        print(f"{pid} v{p.version} class={p.resource_class} risk={p.risk_class.value} "
              f"enabled={p.enabled} ops={','.join(o.value for o in p.allowed_operations)} "
              f"dir={p.exact_target_dir}")


def cmd_targets(e):
    for pid, m in e.targets.items():
        for name, t in m.items():
            print(f"{pid} {name} -> {t.resolved_path} enabled={t.enabled}")


def cmd_budgets(e):
    for pid in e.profiles:
        print(f"{pid}: {e._budget.circuit_state(pid)}")
        print(f"   budget: {e._budget.budget_status(pid, e.profiles[pid].budget)}")


def cmd_disabled(e):
    for pid, p in e.profiles.items():
        if not p.enabled:
            print(pid)


def cmd_inspect(e, pid):
    if pid not in e.profiles:
        print(f"unknown profile {pid}")
        return 1
    p = e.profiles[pid]
    print(vars(p))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="agent.production_policy.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("profiles")
    sub.add_parser("targets")
    sub.add_parser("budgets")
    sub.add_parser("disabled")
    sp = sub.add_parser("inspect-profile"); sp.add_argument("id")
    args = ap.parse_args(argv)
    e = _engine()
    if args.cmd == "status":
        cmd_status(e)
    elif args.cmd == "profiles":
        cmd_profiles(e)
    elif args.cmd == "targets":
        cmd_targets(e)
    elif args.cmd == "budgets":
        cmd_budgets(e)
    elif args.cmd == "disabled":
        cmd_disabled(e)
    elif args.cmd == "inspect-profile":
        return cmd_inspect(e, args.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
