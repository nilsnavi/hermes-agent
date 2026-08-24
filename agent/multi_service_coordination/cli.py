"""Sprint 1.3.15 — read-only CLI.

    python -m agent.multi_service_coordination.cli inspect-plan      <id>
    python -m agent.multi_service_coordination.cli inspect-transaction <id>
    python -m agent.multi_service_coordination.cli inspect-graph
    python -m agent.multi_service_coordination.cli shadow-evaluate   [--n 500]

There is intentionally NO execute command.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from ._durable import CoordinationStore
from .registry import CoordinationRegistry
from .evaluation import run_shadow_study
from . import flags
from .lock_order import canonical_lock_order


def _default_store() -> CoordinationStore:
    base = Path(
        os.environ.get(
            "HERMES_MULTI_SERVICE_COORD_V2_STORE",
            str(Path.home() / ".hermes" / "multi-service-coordination-state"),
        )
    )
    return CoordinationStore(base)


def cmd_inspect_plan(args) -> int:
    store = _default_store()
    txid = args.transaction_id
    rec = store.get_global(txid)
    if rec is None:
        print(f"transaction {txid}: not found", file=sys.stderr)
        return 1
    print(json.dumps(rec, indent=2, sort_keys=True, default=str))
    return 0


def cmd_inspect_transaction(args) -> int:
    store = _default_store()
    rec = store.get_global(args.transaction_id)
    if rec is None:
        print(f"transaction {args.transaction_id}: not found", file=sys.stderr)
        return 1
    print(json.dumps(rec, indent=2, sort_keys=True, default=str))
    print("children:", json.dumps(store.list_children(args.transaction_id), indent=2, default=str))
    print("recovery:", json.dumps(store.get_recovery(args.transaction_id), indent=2, default=str))
    return 0


def cmd_inspect_graph(_args) -> int:
    reg = CoordinationRegistry()
    print(
        json.dumps(
            {
                "registry_digest": reg.registry_digest,
                "services": list(reg.service_ids()),
                "max_services": reg.MAX_SERVICES,
                "max_depth": reg.MAX_DEPTH,
                "max_edges": reg.MAX_EDGES,
                "canonical_lock_order": {
                    s: canonical_lock_order([s])[0] for s in reg.service_ids()
                },
                "flags": {
                    "enabled": flags.multi_coord_enabled(),
                    "mode": flags.multi_coord_mode(),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_shadow_evaluate(args) -> int:
    root = Path(tempfile.mkdtemp(prefix="msc-shadow-eval-"))
    report = run_shadow_study(root, evaluations=args.n)
    print(
        json.dumps(
            {
                "evaluations": report.evaluations,
                "correctness": report.correctness,
                "factivities": report.case_counts,
                "mutations": report.mutations,
                "adapter_calls": report.adapter_calls,
                "failures": report.failures,
                "real_multi_service_adapter_calls": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent.multi_service_coordination.cli",
        description="Sprint 1.3.15 multi-service coordination — SHADOW/REHEARSAL ONLY",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect-plan", help="inspect a global transaction record")
    p.add_argument("transaction_id")
    p.set_defaults(func=cmd_inspect_plan)

    p = sub.add_parser("inspect-transaction", help="inspect a global transaction + children")
    p.add_argument("transaction_id")
    p.set_defaults(func=cmd_inspect_transaction)

    p = sub.add_parser("inspect-graph", help="inspect registry/graph/canonical lock order")
    p.set_defaults(func=cmd_inspect_graph)

    p = sub.add_parser("shadow-evaluate", help="run the read-only shadow study")
    p.add_argument("--n", type=int, default=500)
    p.set_defaults(func=cmd_shadow_evaluate)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())