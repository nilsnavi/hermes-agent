"""Gateway V2 CLI (Sprint 1.0.6) — status / schema gate / demos.

Usage:
    python -m agent.gateway_v2.cli status                 [--db PATH]
    python -m agent.gateway_v2.cli schema-check [--db PATH]   (ZERO writes)
    python -m agent.gateway_v2.cli schema-apply [--db PATH]   (explicit additive)
    python -m agent.gateway_v2.cli shadow-demo               (synthetic, no tools)
    python -m agent.gateway_v2.cli canary-demo               (temp DB, read-only fake)

Default --db: production state.db (schema commands open it READ-ONLY for
check; apply is explicit and additive-only).
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

from agent.execution.registry import SideEffectClass, ToolMetadata, ToolRegistry

from .adapter import GatewayV2Adapter, V2CanaryPolicy
from .context_builder import GatewayRequest
from .flags import read_flags
from .store_factory import schema_apply, schema_check

_DEFAULT_DB = os.path.expanduser("~/.hermes/state.db")


def _demo_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register("search", lambda a, c: {"hits": 2},
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY))
    reg.register("runtime_status", lambda a, c: {"gateway": "active"},
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY))
    return reg


def _cmd_status(args) -> int:
    flags = read_flags()
    db = args.db or _DEFAULT_DB
    check = schema_check(db) if os.path.exists(db) else None
    print(json.dumps({
        "flags": flags.to_dict(),
        "mode": flags.mode(),
        "schema_ready": bool(check and not check["v2_tables_missing"]),
        "v2_tables_present": (check or {}).get("v2_tables_present", []),
        "canary_policy": V2CanaryPolicy().summary(),
    }, ensure_ascii=False, indent=2))
    return 0


def _cmd_schema_check(args) -> int:
    db = args.db or _DEFAULT_DB
    print(json.dumps(schema_check(db), ensure_ascii=False, indent=2))
    return 0


def _cmd_schema_apply(args) -> int:
    db = args.db or _DEFAULT_DB
    before = schema_check(db)
    if not args.yes and before["v2_tables_missing"]:
        print(f"Will add {len(before['v2_tables_missing'])} agent_v2 tables to {db} "
              f"(additive only). Re-run with --yes to confirm.")
        return 2
    result = schema_apply(db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_shadow_demo(args) -> int:
    from .shadow import ShadowRunner

    flags = read_flags()
    request = GatewayRequest(
        request_id=f"shadow-{int(datetime.now(timezone.utc).timestamp())}",
        user_id="demo", session_id="demo", request_type="chat",
        goal="demo shadow",
        allowed_tools=["search", "runtime_status"],
        metadata={"runtime_v2": True},
    )
    report = ShadowRunner(_demo_registry()).run_shadow(
        request,
        step_specs=[{"name": "s1", "tool": "search"},
                    {"name": "s2", "tool": "runtime_status"}],
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("note: zero tool executions, zero production writes")
    return 0


def _cmd_shadow_suite(args) -> int:
    """Sprint 1.0.6.1 §27-32: run the S1..S6 controlled shadow scenario
    suite with the CURRENT environment flags (production flags when run
    under the gateway env). Zero tool executions, zero DB writes, zero
    user-visible output. Output: flags + comparison table (labels only,
    no request content)."""
    from .adapter import GatewayV2Adapter
    from .comparison import build_comparison
    from .shadow_policy import V2ShadowPolicy
    from time import perf_counter

    flags = read_flags()
    adapter = GatewayV2Adapter(flags=flags,
                               shadow_policy=V2ShadowPolicy())
    cases = [
        # (label, goal, step_specs, risk_level)
        ("S1", "Summarize this supplied synthetic text",
         [{"name": "s1", "tool": "search"}], "low"),
        ("S2", "look up runtime status",
         [{"name": "s1", "tool": "runtime_status"}], "low"),
        ("S3", "create/update something on the server",
         [{"name": "s1", "tool": "send_message"}], "low"),
        ("S4", "read sensitive summary",
         [{"name": "s1", "tool": "search"}], "critical"),
        ("S5", "do the impossible",
         [{"name": "s1", "tool": "ghost_tool"}], "low"),
        ("S6", "boom case",
         [], "low"),  # no step_specs → NO_PLAN (benign no-plan outcome)
    ]
    ts = int(datetime.now(timezone.utc).timestamp())
    rows = []
    for label, goal, step_specs, risk in cases:
        request = GatewayRequest(
            request_id=f"{label}-shadow-{ts}", user_id="internal",
            session_id="shadow-suite", request_type="internal", goal=goal,
            risk_level=risk, metadata={"runtime_v2_shadow": True},
        )
        decision = adapter.decide(request)
        t0 = perf_counter()
        report = adapter.shadow(request, step_specs=step_specs, timeout=1.0)
        duration_ms = (perf_counter() - t0) * 1000.0
        comp = build_comparison(request.request_id, report,
                                legacy_success=True, duration_ms=duration_ms)
        rows.append({
            "label": label,
            "decision": decision.value,
            "plan_valid": report.get("plan_valid"),
            "predicted_tools": report.get("predicted_tool_calls"),
            "write": report.get("would_require_write"),
            "approval": report.get("would_require_approval"),
            "actual_v2_tools": 0,
            "mismatch": comp.mismatch_flags,
            "duration_ms": comp.duration_ms,
        })
    print(json.dumps({
        "flags": flags.to_dict(),
        "mode": flags.mode(),
        "rows": rows,
    }, ensure_ascii=False, indent=2))
    return 0


def _cmd_canary_suite(args) -> int:
    """Sprint 1.0.6.2 §47-48: controlled READ-ONLY canary batch C1..C8.

    Runs the production canary path (adapter → SafeCanaryToolRegistry →
    RuntimeOrchestrator → SQLiteExecutionStore) with the CURRENT env
    flags. By default writes to the PRODUCTION state.db agent_v2 tables
    (that IS the point — durable AgentRun); --temp uses a throwaway DB.

    C1-C7 write-intent/critical/invalid cases are classified, never
    executed; only READ_ONLY tools can ever run. C8 is an ordinary
    non-eligible request → LEGACY.
    """
    from .adapter import GatewayV2Adapter
    from .canary import V2CanaryPolicy, default_canary_registry
    from .context_builder import GatewayRequest
    from .flags import read_flags
    from time import perf_counter

    flags = read_flags()
    reg = default_canary_registry()
    # Harness-only READ_ONLY probes for the failure/timeout cases (§26-27).
    reg.register("flaky_probe", lambda a, c: (_ for _ in ()).throw(RuntimeError("injected read failure")),
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY,
                                       timeout=2.0))
    reg.register("slow_probe", _slow_probe,
                 metadata=ToolMetadata(idempotent=True,
                                       side_effect_class=SideEffectClass.READ_ONLY,
                                       timeout=1.0))
    policy = V2CanaryPolicy(allowed_users=["internal"],
                            allowed_sessions=["canary-suite"],
                            allowed_request_types=["internal"], registry=reg)
    adapter = GatewayV2Adapter(flags=flags, registry=reg, canary_policy=policy)
    db_path = None if args.temp else _DEFAULT_DB

    cases = [
        # (label, goal, step_specs, risk, eligible)
        ("C1", "runtime status read",
         [{"name": "s1", "tool": "runtime_status"}], "low", True),
        ("C2", "runtime status read again",
         [{"name": "s1", "tool": "runtime_status"}], "low", True),
        ("C3", "invalid plan probe",
         [{"name": "s1", "tool": "ghost_tool"}], "low", True),
        ("C4", "write intent",
         [{"name": "s1", "tool": "send_message"}], "low", True),
        ("C5", "critical risk read",
         [{"name": "s1", "tool": "runtime_status"}], "critical", True),
        ("C6", "read-only failure",
         [{"name": "s1", "tool": "flaky_probe"}], "low", True),
        ("C6b", "read-only timeout",
         [{"name": "s1", "tool": "slow_probe"}], "low", True),
        ("C7", "ping probe",
         [{"name": "s1", "tool": "canary_ping"}], "low", True),
        ("C7b", "ping probe again",
         [{"name": "s1", "tool": "canary_ping"}], "low", True),
        ("C7c", "status read third",
         [{"name": "s1", "tool": "runtime_status"}], "low", True),
        ("C8", "ordinary non-eligible",
         [{"name": "s1", "tool": "runtime_status"}], "low", False),
    ]
    ts = int(datetime.now(timezone.utc).timestamp())
    rows = []
    for label, goal, step_specs, risk, eligible in cases:
        metadata = {"runtime_v2_canary": True} if eligible else {}
        request = GatewayRequest(
            request_id=f"{label}-canary-{ts}", user_id="internal",
            session_id="canary-suite", request_type="internal", goal=goal,
            risk_level=risk, metadata=metadata,
        )
        decision = adapter.decide(request)
        t0 = perf_counter()
        response = adapter.run_canary(request, step_specs=step_specs,
                                      db_path=db_path, allow_production=True)
        duration_ms = (perf_counter() - t0) * 1000.0
        rows.append({
            "label": label,
            "decision": decision.value,
            "code": response.get("code"),
            "status": response.get("status"),
            "ok": response.get("ok"),
            "tool_calls": response.get("tool_calls", 0),
            "duration_ms": round(duration_ms, 3),
        })
    print(json.dumps({
        "flags": flags.to_dict(),
        "db": "production state.db" if not args.temp else "temp",
        "rows": rows,
    }, ensure_ascii=False, indent=2))
    return 0


def _slow_probe(arguments, context):
    import time

    time.sleep(6)  # exceeds ToolMetadata(timeout=1.0) → TOOL_FAILED(timeout)
    return {"ok": True}


def _cmd_canary_demo(args) -> int:
    flags = read_flags().from_mapping({
        "HERMES_RUNTIME_V2_ENABLED": "true",
        "HERMES_RUNTIME_V2_PERSISTENCE": "true",
        "HERMES_RUNTIME_V2_CANARY": "true",
    })
    adapter = GatewayV2Adapter(flags=flags, registry=_demo_registry(),
                               canary_policy=V2CanaryPolicy(
                                   allowed_users=["demo"],
                                   registry=_demo_registry()))
    request = GatewayRequest(
        request_id=f"canary-{int(datetime.now(timezone.utc).timestamp())}",
        user_id="demo", session_id="demo", request_type="chat",
        goal="demo canary", allowed_tools=["search", "runtime_status"],
        metadata={"runtime_v2": True},
    )
    response = adapter.run_canary(
        request,
        step_specs=[{"name": "s1", "tool": "search"},
                    {"name": "s2", "tool": "runtime_status"}],
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agent.gateway_v2.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status")
    p.add_argument("--db", default=None)
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("schema-check")
    p.add_argument("--db", default=None)
    p.set_defaults(func=_cmd_schema_check)

    p = sub.add_parser("schema-apply")
    p.add_argument("--db", default=None)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=_cmd_schema_apply)

    sub.add_parser("shadow-demo").set_defaults(func=_cmd_shadow_demo)
    sub.add_parser("shadow-suite").set_defaults(func=_cmd_shadow_suite)
    p = sub.add_parser("canary-suite")
    p.add_argument("--temp", action="store_true",
                   help="use a throwaway temp DB instead of production state.db")
    p.set_defaults(func=_cmd_canary_suite)
    sub.add_parser("canary-demo").set_defaults(func=_cmd_canary_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
