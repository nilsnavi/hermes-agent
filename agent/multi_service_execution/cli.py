"""Sprint 1.3.17 — read-only multi-service execution CLI.

    python -m agent.multi_service_execution.cli status
    python -m agent.multi_service_execution.cli inspect-plan <id>
    python -m agent.multi_service_execution.cli inspect-receipt <id>
    python -m agent.multi_service_execution.cli dry-run <tx>

Read-only.  There is NO execution/mutate/commit subcommand.  The dry-run only
classifies against durable idempotency state; it never drives an adapter.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _root() -> Path:
    return Path(os.environ.get(
        "HERMES_MULTI_SERVICE_EXECUTION_STORE",
        str(Path.home() / ".hermes" / "multi-service-execution-state"),
    ))


def _idem():
    from .idempotency import ExecutionIdempotencyStore
    return ExecutionIdempotencyStore(_root())


def _receipts():
    from .receipt import ExecutionReceiptStore
    return ExecutionReceiptStore(_root())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="msexec",
                                description="Read-only multi-service execution CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "inspect-plan", "inspect-receipt", "dry-run"):
        sp = sub.add_parser(name)
        sp.add_argument("arg", nargs="?", default="")
    a = p.parse_args(argv)

    if a.cmd == "status":
        idem = _idem()
        receipts = _receipts()
        print(json.dumps({
            "idempotency_records": len(idem.all()),
            "receipts": len([r for r in _all_receipts(receipts)]),
            "real_adapter_calls": 0,
            "real_compensation_adapter_calls": 0,
        }, indent=2, sort_keys=True))
        return 0

    if a.cmd == "dry-run":
        # classify only: does a terminal result already exist for this tx?
        idem = _idem()
        matches = [k for k, r in idem.all().items()
                   if (r.get("result") or {}).get("execution_id", "").find(a.arg.split(":")[-1]) != -1 or a.arg in k]
        print(json.dumps({"classified": True, "terminal_prior": bool(matches)}, indent=2, sort_keys=True))
        return 0

    if a.cmd == "inspect-plan":
        return _emit(_plan_lookup(a.arg))

    if a.cmd == "inspect-receipt":
        receipts = _receipts()
        rec = receipts.get(a.arg)
        if rec is None:
            print(json.dumps({"error": "receipt not found"}, indent=2, sort_keys=True))
            return 1
        print(json.dumps(rec, indent=2, sort_keys=True))
        return 0
    return 2


def _plan_lookup(aid: str):
    # plans are not persisted in 1.3.17 (in-memory); report read-only status
    return {"inspect_plan": aid, "note": "plans are runtime objects; not persisted",
            "real_adapter_calls": 0}


def _emit(obj) -> int:
    print(json.dumps(obj, indent=2, sort_keys=True))
    return 0


def _all_receipts(receipts):
    # list receipts by scanning the store raw keys
    try:
        import copy
        data = receipts._tx.read().get("receipts", {})
        return [copy.deepcopy(r) for r in data.values()]
    except Exception:
        return []


if __name__ == "__main__":
    sys.exit(main())