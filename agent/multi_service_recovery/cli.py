"""Sprint 1.3.16 — read-only recovery CLI.  NO execute.  NO mutate.

    python -m agent.multi_service_recovery.cli recovery status <tx>
    python -m agent.multi_service_recovery.cli recovery inspect <tx>
    python -m agent.multi_service_recovery.cli recovery classify <tx>
    python -m agent.multi_service_recovery.cli recovery events <tx>
    python -m agent.multi_service_recovery.cli recovery compensation-plan <tx>
    python -m agent.multi_service_recovery.cli recovery dry-run <tx>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _store():
    from .store import RecoveryStore
    base = Path(os.environ.get(
        "HERMES_MULTI_SERVICE_RECOVERY_STORE",
        str(Path.home() / ".hermes" / "multi-service-recovery-state"),
    ))
    host = os.environ.get("HERMES_RECOVERY_HOST_IDENTITY", "localhost")
    return RecoveryStore(base, host_identity=host)


def _load_tx(tx_id):
    store = _store()
    journal = store.journal.types()
    claims = store.claims.get(tx_id, 0)
    return store, journal, claims


def _classify(tx_id):
    from .clock import TrustedClock
    from .coordinator import MultiServiceRecoveryCoordinator
    from .provenance import Provenance
    store = _store()
    journal = store.journal.types()
    prov = Provenance(host_identity=store.host_identity)
    coord = MultiServiceRecoveryCoordinator(
        store, provenance=prov, clock=TrustedClock(),
        transaction_id=tx_id, semantic_key=tx_id, baseline_sha="",
        plan_hash="", graph_digest="", service_set=(), recovery_generation=1)
    return coord.recover(journal_types=journal)


def _print_plan(plan):
    return {
        "transaction_id": plan.transaction_id,
        "disposition": plan.disposition.value,
        "crash_point": plan.crash_point,
        "violation": plan.violation,
        "would_verify": plan.would_verify,
        "would_compensate": plan.would_compensate,
        "manual_review": plan.manual_review,
        "conflicts": list(plan.conflicts),
        "real_adapter_calls": 0,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="recovery", description="Read-only recovery CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "inspect", "classify", "events", "compensation-plan", "dry-run"):
        sp = sub.add_parser(name)
        sp.add_argument("tx_id")
    a = p.parse_args(argv)

    if a.cmd in ("status", "inspect", "classify", "dry-run"):
        plan = _classify(a.tx_id)
        out = _print_plan(plan)
        if a.cmd == "dry-run":
            out = {
                "disposition": plan.disposition.value,
                "would_verify": plan.would_verify,
                "would_compensate": plan.would_compensate,
                "manual_review": plan.manual_review,
                "conflicts": list(plan.conflicts),
                "real_adapter_calls": 0,
            }
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    if a.cmd == "events":
        _, journal, _ = _load_tx(a.tx_id)
        print(json.dumps({"events": journal}, indent=2, sort_keys=True))
        return 0
    if a.cmd == "compensation-plan":
        store, _, _ = _load_tx(a.tx_id)
        comp = [r for r in store.compensation._tx.read().values()]  # noqa: SLF001
        print(json.dumps({"compensation": comp}, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())