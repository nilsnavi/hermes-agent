"""Sprint 1.3.12 — read-only restart foundation CLI.

Commands (all read-only / analysis):
  status                 — registry + flags + guard state
  inspect <service>      — profile + current identity observation
  eligibility <service>  — eligibility analysis (fail-closed)
  transition-plan <service> — modelled PID stop/start transition plan
  quiescence-plan <service>  — quiescence + orphan plan
  recovery-plan <service>    — crash recovery + rollback plan

There is intentionally NO execute verb.
"""
from __future__ import annotations

import argparse
import sys

from . import flags
from .eligibility import EligibilityReason, evaluate_eligibility
from .gateway import gateway_restart_capability
from .guard import (adapter_calls, accepts_arbitrary_unit,
                     accepts_raw_command, restart_execution_guard)
from .registry import default_registry


def _service_profile(service_id: str):
    reg = default_registry()
    return reg.get(service_id)


def _obs_ctx_for(service_id: str) -> dict:
    """A passing-everything context for shadow eligibility analysis."""
    return {
        "identity_verified": True,
        "graph_status": "HEALTHY",
        "critical_dependents": 0,
        "active_dependents": 0,
        "blast_radius": "SERVICE",
        "criticality": "LOW",
        "stop_contract_known": True,
        "quiescence_proven": True,
        "orphan_risk": False,
        "start_contract_known": True,
        "executable_verified": True,
        "port_transition_proven": True,
        "health_pass": True,
        "rollback_proven": True,
        "risk_class": "HIGH",
        "restart_rollback_proven": True,
    }


def cmd_status(args) -> int:
    reg = default_registry()
    print("RESTART FOUNDATION STATUS (Sprint 1.3.12)")
    print(f"  flag_enabled  : {flags.enabled()}")
    print(f"  mode          : {flags.mode()}")
    print(f"  restart_authority: {flags.restart_authority()}")
    print(f"  adapter_calls : {adapter_calls()}")
    print(f"  accepts_raw   : {accepts_raw_command()}")
    print(f"  accepts_unit  : {accepts_arbitrary_unit()}")
    print(f"  guard         : {restart_execution_guard()}")
    print(f"  gateway       : {gateway_restart_capability().result} exec={gateway_restart_capability().execution}")
    print(f"  registered services: {[p.service_id for p in reg.all()]}")
    p = reg.get("hermes-aux-canary")
    if p is not None:
        print(f"  hermes-aux-canary class={p.service_class} risk={p.risk_class} "
              f"authority={p.restart_authority_enabled}")
    return 0


def cmd_inspect(args) -> int:
    p = _service_profile(args.service)
    if p is None:
        print(f"no profile for {args.service}", file=sys.stderr)
        return 1
    print(f"PROFILE {p.service_id}")
    print(f"  unit            : {p.unit_name}")
    print(f"  class           : {p.service_class}")
    print(f"  criticality     : {p.criticality}")
    print(f"  restart_supported : {p.restart_supported}")
    print(f"  expected_executable : {p.expected_executable}")
    print(f"  expected_user      : {p.expected_user}")
    print(f"  expected_ports      : {list(p.expected_ports)}")
    print(f"  quiescence_policy   : {p.quiescence_policy}")
    print(f"  rollback_strategy   : {p.rollback_strategy}")
    print(f"  risk_class          : {p.risk_class}")
    print(f"  blast_radius_ceiling: {p.blast_radius_ceiling}")
    print(f"  restart_authority_enabled: {p.restart_authority_enabled}")
    return 0


def cmd_eligibility(args) -> int:
    p = _service_profile(args.service)
    if p is None:
        print(f"no profile for {args.service}", file=sys.stderr)
        return 1
    reason = evaluate_eligibility(p, _obs_ctx_for(args.service))
    print(f"ELIGIBILITY {args.service}: {reason.value}")
    if reason != EligibilityReason.ELIGIBLE_FOR_FUTURE_RESTART_CANARY:
        print("  (ELIGIBLE != AUTHORIZED; execution guard blocks regardless)")
    return 0


def cmd_transition_plan(args) -> int:
    p = _service_profile(args.service)
    if p is None:
        print(f"no profile for {args.service}", file=sys.stderr)
        return 1
    print(f"TRANSITION PLAN {args.service} (model only, 0 mutation)")
    print(f"  old_pid_identity: {p.unit_name}/main-pid")
    print(f"  expected_old_pid_behavior : {p.expected_old_pid_behavior}")
    print(f"  expected_new_pid_behavior : {p.expected_new_pid_behavior}")
    print(f"  stop_timeout : {p.expected_stop_timeout}")
    print(f"  start_timeout: {p.expected_start_timeout}")
    print(f"  execution    : {restart_execution_guard(service_id=args.service)}")
    return 0


def cmd_quiescence_plan(args) -> int:
    p = _service_profile(args.service)
    if p is None:
        print(f"no profile for {args.service}", file=sys.stderr)
        return 1
    print(f"QUIESCENCE PLAN {args.service} (model only)")
    print(f"  policy          : {p.quiescence_policy}")
    print(f"  expected_ports  : {list(p.expected_ports)}")
    print("  checks: old_pid_gone, no_children, no_orphans, ports_released, unit_stopped")
    return 0


def cmd_recovery_plan(args) -> int:
    p = _service_profile(args.service)
    if p is None:
        print(f"no profile for {args.service}", file=sys.stderr)
        return 1
    print(f"RECOVERY PLAN {args.service} (analysis only, 0 mutation)")
    print(f"  rollback_strategy : {p.rollback_strategy}")
    print("  unknown_outcome   : do NOT blindly start / restart; reconcile")
    print("  restart-as-rollback: HARD DENIED")
    print(f"  execution         : {restart_execution_guard(service_id=args.service)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent.service_restart_foundation.cli",
        description="Read-only restart foundation analysis (Sprint 1.3.12).",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="registry + flags + guard state").set_defaults(func=cmd_status)

    p_inspect = sub.add_parser("inspect", help="inspect a service profile")
    p_inspect.add_argument("service")
    p_inspect.set_defaults(func=cmd_inspect)

    p_elig = sub.add_parser("eligibility", help="eligibility analysis")
    p_elig.add_argument("service")
    p_elig.set_defaults(func=cmd_eligibility)

    p_tp = sub.add_parser("transition-plan", help="modelled PID transition plan")
    p_tp.add_argument("service")
    p_tp.set_defaults(func=cmd_transition_plan)

    p_qp = sub.add_parser("quiescence-plan", help="quiescence + orphan plan")
    p_qp.add_argument("service")
    p_qp.set_defaults(func=cmd_quiescence_plan)

    p_rp = sub.add_parser("recovery-plan", help="crash recovery + rollback plan")
    p_rp.add_argument("service")
    p_rp.set_defaults(func=cmd_recovery_plan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())