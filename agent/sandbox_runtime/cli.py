"""Sandbox runtime CLI (Sprint 1.3.5 §31) — read-only operational CLI.

    python -m agent.sandbox_runtime.cli status
    python -m agent.sandbox_runtime.cli transactions
    python -m agent.sandbox_runtime.cli inspect <txid>
    python -m agent.sandbox_runtime.cli verify <txid>

Mutation CLI exists ONLY for explicit sandbox demo and requires BOTH
``--sandbox`` AND ``--confirm``. No default mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _root_from_args(args) -> str:
    return os.path.abspath(os.path.expanduser(args.root))


def cmd_status(args) -> int:
    from .health import check_sandbox_health
    from .flags import flags_from_env
    from .root import SandboxRoot
    root = SandboxRoot(_root_from_args(args))
    health = check_sandbox_health(root)
    flags = flags_from_env()
    print(json.dumps({
        "sandbox_root": root.root,
        "exists": root.exists(),
        "mode": oct(os.stat(root.root).st_mode & 0o777)
        if root.exists() else None,
        "health_ok": health.ok,
        "health_checks": [{"name": n, "ok": ok}
                          for n, ok in health.checks],
        "flags": flags.to_dict(),
        "mutation_allowed": flags.mutation_allowed,
    }, indent=2))
    return 0 if health.ok else 1


def cmd_transactions(args) -> int:
    from .recovery import read_transaction_records
    from .root import SandboxRoot
    root = SandboxRoot(_root_from_args(args))
    if not root.exists():
        print("[]", file=sys.stderr)
        return 0
    rows = [{"idempotency_key": r.get("idempotency_key"),
             "status": r.get("status"),
             "txid": r.get("txid"),
             "operation": r.get("operation"),
             "target": r.get("target")}
            for r in read_transaction_records(root)]
    print(json.dumps(rows, indent=2))
    return 0


def cmd_inspect(args) -> int:
    from .recovery import read_transaction_records
    from .root import SandboxRoot
    root = SandboxRoot(_root_from_args(args))
    if not root.exists():
        print("[]", file=sys.stderr)
        return 1
    for r in read_transaction_records(root):
        if r.get("txid") == args.txid or \
                r.get("idempotency_key") == args.txid:
            print(json.dumps(r, indent=2, default=str))
            return 0
    print(f"transaction {args.txid} not found", file=sys.stderr)
    return 1


def cmd_verify(args) -> int:
    from .recovery import classify_incomplete, read_transaction_records
    from .root import SandboxRoot
    root = SandboxRoot(_root_from_args(args))
    if not root.exists():
        print("[]", file=sys.stderr)
        return 1
    for r in read_transaction_records(root):
        if r.get("txid") == args.txid:
            verdict = classify_incomplete(r)
            print(json.dumps({
                "txid": r.get("txid"),
                "status": r.get("status"),
                "verdict": verdict,
                "manual_review_required": verdict == "UNKNOWN_OUTCOME",
                "read_only": True,
            }, indent=2))
            return 0
    print(f"transaction {args.txid} not found", file=sys.stderr)
    return 1


def cmd_incomplete(args) -> int:
    from .recovery import RecoveryDisposition, scan_incomplete_transactions
    from .root import SandboxRoot
    root = SandboxRoot(_root_from_args(args))
    rows = [] if not root.exists() else [
        row.to_dict() for row in scan_incomplete_transactions(root, limit=args.limit)
        if row.disposition is not RecoveryDisposition.TERMINAL]
    print(json.dumps(rows, indent=2, default=str))
    return 0


def cmd_recovery_status(args) -> int:
    from collections import Counter
    from .recovery import RecoveryDisposition, scan_incomplete_transactions
    from .root import SandboxRoot
    root = SandboxRoot(_root_from_args(args))
    rows = [] if not root.exists() else scan_incomplete_transactions(root,
                                                                      limit=args.limit)
    rows = [row for row in rows
            if row.disposition is not RecoveryDisposition.TERMINAL]
    counts = Counter(row.disposition.value for row in rows)
    print(json.dumps({"incomplete_count": len(rows),
                      "dispositions": dict(sorted(counts.items())),
                      "read_only": True}, indent=2))
    return 0


def cmd_manual_reviews(args) -> int:
    from .manual_review import ManualReviewStore
    from .root import SandboxRoot
    root = SandboxRoot(_root_from_args(args))
    if not root.exists():
        print("[]")
        return 0
    store = ManualReviewStore(root)
    if args.review_id:
        try:
            rows = [store.inspect(args.review_id).to_dict()]
        except KeyError:
            print(f"manual review {args.review_id} not found", file=sys.stderr)
            return 1
    else:
        rows = [item.to_dict() for item in store.list(limit=args.limit)]
    print(json.dumps(rows, indent=2, default=str))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="sandbox_runtime",
        description="Sandbox mutation runtime (Sprint 1.3.5) — "
                    "read-only by default")
    parser.add_argument("--root", default="~/.hermes/sandbox/system-mutation",
                        help="sandbox root (default: persistent Hermes root)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="sandbox status + health")
    p_status.add_argument("--root", default=argparse.SUPPRESS,
                          help=argparse.SUPPRESS)
    p_status.set_defaults(func=cmd_status)

    p_tx = sub.add_parser("transactions", help="list transactions")
    p_tx.add_argument("--root", default=argparse.SUPPRESS,
                      help=argparse.SUPPRESS)
    p_tx.set_defaults(func=cmd_transactions)

    p_inspect = sub.add_parser("inspect", help="inspect one transaction")
    p_inspect.add_argument("txid")
    p_inspect.add_argument("--root", default=argparse.SUPPRESS,
                           help=argparse.SUPPRESS)
    p_inspect.set_defaults(func=cmd_inspect)

    p_verify = sub.add_parser("verify", help="verify one transaction")
    p_verify.add_argument("txid")
    p_verify.add_argument("--root", default=argparse.SUPPRESS,
                          help=argparse.SUPPRESS)
    p_verify.set_defaults(func=cmd_verify)

    p_recovery = sub.add_parser("recovery-status", help="summarize incomplete recovery state")
    p_recovery.add_argument("--limit", type=int, default=100)
    p_recovery.add_argument("--root", default=argparse.SUPPRESS,
                            help=argparse.SUPPRESS)
    p_recovery.set_defaults(func=cmd_recovery_status)

    p_incomplete = sub.add_parser("incomplete", help="list incomplete transactions")
    p_incomplete.add_argument("--limit", type=int, default=100)
    p_incomplete.add_argument("--root", default=argparse.SUPPRESS,
                              help=argparse.SUPPRESS)
    p_incomplete.set_defaults(func=cmd_incomplete)

    p_reviews = sub.add_parser("manual-reviews", help="list or inspect manual reviews")
    p_reviews.add_argument("review_id", nargs="?")
    p_reviews.add_argument("--limit", type=int, default=100)
    p_reviews.add_argument("--root", default=argparse.SUPPRESS,
                           help=argparse.SUPPRESS)
    p_reviews.set_defaults(func=cmd_manual_reviews)

    # Backward-compatible alias for a single review inspection
    p_inspect_review = sub.add_parser("inspect-review", help="inspect one manual review (alias)")
    p_inspect_review.add_argument("review_id", help="manual review id")
    p_inspect_review.add_argument("--root", default=argparse.SUPPRESS,
                                  help=argparse.SUPPRESS)
    p_inspect_review.set_defaults(func=cmd_manual_reviews)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
