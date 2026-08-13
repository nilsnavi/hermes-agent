"""Operations CLI (Sprint 1.0.6.3 §20, §38-40, §54-56).

Usage:
    python -m agent.operations_v2.cli runs [--status S] [--task-type T]
                                           [--from TS] [--to TS] [--limit N]
                                           [--json]
    python -m agent.operations_v2.cli run <run-id> [--json]
    python -m agent.operations_v2.cli timeline <run-id> [--limit N]
                                           [--before ID] [--after ID] [--json]
    python -m agent.operations_v2.cli approvals [--json]
    python -m agent.operations_v2.cli approval <id> [--run-id R] [--json]
    python -m agent.operations_v2.cli approve <id> --run-id R --operator O
                                           [--confirm] [--dry-run] [--note N]
                                           [--expected-version V] [--json]
    python -m agent.operations_v2.cli reject <id> --run-id R --operator O
                                           [--confirm] [--dry-run] [--note N] [--json]
    python -m agent.operations_v2.cli expire <id> [--run-id R] [--confirm]
                                           [--dry-run] [--json]
    python -m agent.operations_v2.cli manual-reviews [--json]
    python -m agent.operations_v2.cli stale-runs [--threshold-min N] [--json]
    python -m agent.operations_v2.cli metrics [--window 24h|1h|all] [--json]
    python -m agent.operations_v2.cli health [--json]

Inspection commands are READ-ONLY. Decision commands (approve/reject/
expire) require ``--operator`` AND ``--confirm``; ``--dry-run`` shows
the planned transition with ZERO writes. No accidental Enter-to-approve.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .models import OperatorIdentity

_DEFAULT_DB = os.path.expanduser("~/.hermes/state.db")


def _service(args) -> Any:
    from .service import OperationsService

    db = getattr(args, "db", None) or _DEFAULT_DB
    return OperationsService(db_path=db)


def _emit(value: Any, as_json: bool) -> int:
    if as_json:
        print(_stable_json(value))
    else:
        _print_human(value)
    return 0


def _stable_json(value: Any) -> str:
    from .serializers import to_json

    return to_json(value)


def _print_human(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, list) and item and isinstance(item[0], dict):
                print(f"{key}:")
                for row in item:
                    print("  " + _compact(row))
            elif isinstance(item, dict):
                print(f"{key}: " + _compact(item))
            else:
                print(f"{key}: {item}")
    elif isinstance(value, list):
        for row in value:
            print(_compact(row) if isinstance(row, dict) else row)
    else:
        print(value)


def _compact(mapping: Dict[str, Any]) -> str:
    parts = []
    for key, value in mapping.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        parts.append(f"{key}={value}")
    return " ".join(parts)


# ── inspection commands ──────────────────────────────────────────────


def _cmd_runs(args) -> int:
    svc = _service(args)
    runs = svc.list_runs(
        status=args.status, task_type=args.task_type,
        from_ts=args.from_ts, to_ts=args.to_ts, limit=args.limit,
    )
    return _emit([r.to_dict() for r in runs], args.json)


def _cmd_run(args) -> int:
    svc = _service(args)
    return _emit(svc.get_run(args.run_id).to_dict(), args.json)


def _cmd_timeline(args) -> int:
    svc = _service(args)
    items = svc.timeline(
        args.run_id, limit=args.limit, before=args.before, after=args.after
    )
    return _emit([i.to_dict() for i in items], args.json)


def _cmd_approvals(args) -> int:
    svc = _service(args)
    if not args.all:
        views: List[Any] = svc.pending_approvals()
    else:
        from .run_inspector import RunInspector

        db = getattr(args, "db", None) or _DEFAULT_DB
        views = RunInspector(db).list_approvals(
            run_id=args.run_id, status=args.status, limit=args.limit or 100
        )
    return _emit([v.to_dict() for v in views], args.json)


def _cmd_approval(args) -> int:
    svc = _service(args)
    view = svc.get_approval(args.approval_id, run_id=args.run_id)
    return _emit(view.to_dict(), args.json)


def _cmd_manual_reviews(args) -> int:
    svc = _service(args)
    return _emit([m.to_dict() for m in svc.manual_reviews()], args.json)


def _cmd_stale_runs(args) -> int:
    svc = _service(args)
    return _emit([s.to_dict() for s in svc.stale_runs(args.threshold_min)], args.json)


def _cmd_metrics(args) -> int:
    svc = _service(args)
    return _emit(svc.metrics(args.window), args.json)


def _cmd_health(args) -> int:
    svc = _service(args)
    return _emit(svc.health().to_dict(), args.json)


def _cmd_schema_check(args) -> int:
    from .migration import schema_check

    db = getattr(args, "db", None) or _DEFAULT_DB
    print(_stable_json(schema_check(db)))
    return 0


def _cmd_schema_apply(args) -> int:
    from .migration import ensure_operations_schema

    db = getattr(args, "db", None) or _DEFAULT_DB
    result = ensure_operations_schema(db)
    print(_stable_json(result))
    return 0


# ── decision commands (§38-40) ───────────────────────────────────────


def _operator(args) -> OperatorIdentity:
    return OperatorIdentity(
        operator_id=args.operator or "",
        source="cli",
        roles=frozenset({"operator"}),
        authenticated=bool(args.operator),
    )


def _require_decision_gate(args) -> None:
    if not args.operator:
        print("error: --operator <id> is required for decision commands",
              file=sys.stderr)
        sys.exit(2)
    if not args.confirm:
        print("error: --confirm is required (no accidental approve)",
              file=sys.stderr)
        sys.exit(2)


def _cmd_approve(args) -> int:
    svc = _service(args)
    operator = _operator(args)
    if args.dry_run:
        return _emit(
            svc.approval_dry_run(args.run_id, args.approval_id, operator, "approve"),
            args.json,
        )
    _require_decision_gate(args)
    decision = svc.approve(
        args.run_id, args.approval_id, operator,
        expected_version=args.expected_version, note=args.note,
    )
    return _emit(decision.to_dict(), args.json)


def _cmd_reject(args) -> int:
    svc = _service(args)
    operator = _operator(args)
    if args.dry_run:
        return _emit(
            svc.approval_dry_run(args.run_id, args.approval_id, operator, "reject"),
            args.json,
        )
    _require_decision_gate(args)
    decision = svc.reject(
        args.run_id, args.approval_id, operator,
        expected_version=args.expected_version, note=args.note,
    )
    return _emit(decision.to_dict(), args.json)


def _cmd_expire(args) -> int:
    svc = _service(args)
    if args.dry_run:
        view = svc.get_approval(args.approval_id, run_id=args.run_id)
        return _emit({
            "approval_id": args.approval_id,
            "run_id": view.run_id,
            "current_status": view.status,
            "expected_transition": f"{view.status} -> expired",
            "writes": 0,
        }, args.json)
    _require_decision_gate(args)
    decision = svc.expire(args.approval_id, run_id=args.run_id)
    return _emit(decision.to_dict(), args.json)


# ── resume drill ─────────────────────────────────────────────────────


def _cmd_resume(args) -> int:
    svc = _service(args)
    return _emit(svc.resume(args.run_id), args.json)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agent.operations_v2.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    # --db accepted BEFORE or AFTER the subcommand. Single definition via
    # a parent parser; SUPPRESS default so the top-level value is never
    # clobbered by a subparser default.
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--db", default=argparse.SUPPRESS,
                        help="V2 database (default: state.db)")

    p = sub.add_parser("runs", parents=[parent])
    p.add_argument("--status", default=None)
    p.add_argument("--task-type", default=None)
    p.add_argument("--from", dest="from_ts", default=None)
    p.add_argument("--to", dest="to_ts", default=None)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_runs)

    p = sub.add_parser("run", parents=[parent])
    p.add_argument("run_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("timeline", parents=[parent])
    p.add_argument("run_id")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--before", type=int, default=None)
    p.add_argument("--after", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_timeline)

    p = sub.add_parser("approvals", parents=[parent])
    p.add_argument("--all", action="store_true",
                   help="list all approvals (default: pending only)")
    p.add_argument("--status", default=None, help="filter by status (with --all)")
    p.add_argument("--run-id", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_approvals)

    p = sub.add_parser("approval", parents=[parent])
    p.add_argument("approval_id")
    p.add_argument("--run-id", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_approval)

    p = sub.add_parser("approve", parents=[parent])
    p.add_argument("approval_id")
    p.add_argument("--run-id", required=True)
    p.add_argument("--operator", default=None)
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--note", default=None)
    p.add_argument("--expected-version", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_approve)

    p = sub.add_parser("reject", parents=[parent])
    p.add_argument("approval_id")
    p.add_argument("--run-id", required=True)
    p.add_argument("--operator", default=None)
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--note", default=None)
    p.add_argument("--expected-version", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_reject)

    p = sub.add_parser("expire", parents=[parent])
    p.add_argument("approval_id")
    p.add_argument("--run-id", default=None)
    p.add_argument("--operator", default=None)
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_expire)

    p = sub.add_parser("manual-reviews", parents=[parent])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_manual_reviews)

    p = sub.add_parser("stale-runs", parents=[parent])
    p.add_argument("--threshold-min", type=int, default=60)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_stale_runs)

    p = sub.add_parser("metrics", parents=[parent])
    p.add_argument("--window", choices=["1h", "24h", "all"], default="24h")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_metrics)

    p = sub.add_parser("health", parents=[parent])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_health)

    p = sub.add_parser("resume", parents=[parent])
    p.add_argument("run_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_resume)

    p = sub.add_parser("schema-check", parents=[parent])
    p.set_defaults(func=_cmd_schema_check)

    p = sub.add_parser("schema-apply", parents=[parent])
    p.set_defaults(func=_cmd_schema_apply)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
