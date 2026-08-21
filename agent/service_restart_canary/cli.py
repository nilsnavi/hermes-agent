"""Sprint 1.3.13 — CLI for the single aux restart canary (read-only).

Commands: status, inspect, eligibility, plan, shadow, rehearsal.
No execute command — live restart is only via typed RestartCanaryManager.
"""
from __future__ import annotations

import json
import sys

from .allowlist import default_allowlist, CANARY_SERVICE_ID, CANARY_UNIT
from .flags import canary_active, enabled, mode
from .gateway import gateway_self_control
from .negative_matrix import negative_matrix_ok, negative_matrix_results
from .rehearsal import run_rehearsal, rehearsal_ok
from .shadow import run_shadow_evaluations, shadow_pass


def _status() -> int:
    print(f"canary_enabled={enabled()}")
    print(f"canary_mode={mode()}")
    print(f"canary_active={canary_active()}")
    al = default_allowlist()
    print(f"allowlist_services={list(e.service_id for e in al.exact())}")
    print(f"gateway_self_control={gateway_self_control().result}")
    print(f"kill_switch=True (restart_authority_blocked_until_approval)")
    print(f"negative_matrix_ok={negative_matrix_ok(al)}")
    return 0


def _inspect() -> int:
    al = default_allowlist()
    for e in al.exact():
        print(f"service_id={e.service_id}")
        print(f"unit_name={e.unit_name}")
        print(f"profile_version={e.profile_version}")
        print(f"expected_executable={e.expected_executable}")
        print(f"expected_user={e.expected_user}")
        print(f"expected_cgroup={e.expected_cgroup}")
        print(f"restart_contract_version={e.restart_contract_version}")
    return 0


def _eligibility() -> int:
    al = default_allowlist()
    results = negative_matrix_results(al)
    for r in results:
        print(f"{r.case}: denied={r.denied} reason={r.reason}")
    print(f"negative_matrix_ok={negative_matrix_ok(al)}")
    return 0


def _plan() -> int:
    al = default_allowlist()
    entry = al.entry_for_service(CANARY_SERVICE_ID)
    if entry is None:
        print("ERROR: canary entry not found")
        return 1
    plan = {
        "service_id": entry.service_id,
        "unit_name": entry.unit_name,
        "operation": "RESTART",
        "restart_contract_version": entry.restart_contract_version,
        "expected_executable": entry.expected_executable,
        "expected_user": entry.expected_user,
        "approval_required": True,
        "kill_switch": True,
        "budget": {"max_success": 1, "max_attempts": 2},
    }
    print(json.dumps(plan, indent=2))
    return 0


def _shadow() -> int:
    results = run_shadow_evaluations(n=50)
    ok = shadow_pass(results)
    print(f"shadow_evaluations={len(results)}")
    print(f"shadow_pass={ok}")
    print(f"shadow_mutations=0")
    return 0 if ok else 1


def _rehearsal() -> int:
    result = run_rehearsal()
    ok = rehearsal_ok(result)
    print(f"total_scenarios={result['total_scenarios']}")
    print(f"violations={result['violations']}")
    print(f"mutations={result['mutations']}")
    print(f"by_category={json.dumps(result['by_category'])}")
    return 0 if ok else 1


_COMMANDS = {
    "status": _status,
    "inspect": _inspect,
    "eligibility": _eligibility,
    "plan": _plan,
    "shadow": _shadow,
    "rehearsal": _rehearsal,
}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print("Usage: python -m agent.service_restart_canary.cli <status|inspect|"
              "eligibility|plan|shadow|rehearsal>")
        return 0
    cmd = argv[0]
    fn = _COMMANDS.get(cmd)
    if fn is None:
        print(f"ERROR: unknown command '{cmd}' (read-only CLI, no execute)")
        return 1
    return fn()


if __name__ == "__main__":
    raise SystemExit(main())