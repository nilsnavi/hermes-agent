"""``python -m agent.shadow_worker`` -- independent executable entrypoint.

Read-only by design: this CLI never activates a live hook, never starts against
the production gateway, and never writes/restarts anything.  With no subcommand
it prints the safe defaults.  ``--trace`` builds the standalone runner and runs
one bounded envelope to prove independent executability (still shadow-only).
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import WorkerConfig
from .envelope import (
    ENVELOPE_SCHEMA_VERSION,
    ProductionShadowEnvelopeV1,
    default_timestamp,
    new_event_id,
)
from .transport import QueueOneWayTransport
from .worker import ShadowWorker, WorkerStatus


def _safe_defaults() -> dict[str, object]:
    cfg = WorkerConfig.from_mapping(None)
    return {
        "phase": "8.3",
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "live_activation": False,
        "config": cfg.as_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent.shadow_worker",
        description="Isolated Shadow Worker CLI (read-only, Phase 8.3)",
    )
    parser.add_argument("--trace", action="store_true",
                        help="build standalone runner + process one bounded synthetic envelope")
    args = parser.parse_args(argv)

    if not args.trace:
        json.dump(_safe_defaults(), sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    # Sandboxed trace: worker is OFF / kill switch ON by default, so we build and
    # prove the plumbing without any live activation.
    config = WorkerConfig.from_mapping(None)  # safe defaults (kill switch ON)
    transport = QueueOneWayTransport(max_depth=16)
    from .standalone import build_standalone_runner
    from .audit import WorkerAuditStore
    from .metrics import WorkerMetrics
    worker = ShadowWorker(config=config, transport=transport,
                          runner=build_standalone_runner(),
                          metrics=WorkerMetrics(), audit=WorkerAuditStore())

    env = ProductionShadowEnvelopeV1(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        event_id=new_event_id(),
        source_request_id="trace-1", tenant_id="trace", user_id="u",
        request_kind="monitoring",
        sanitized_payload={"q": "standalone trace"},
        input_digest="in-1", production_timestamp=default_timestamp(),
        trace_id="trace", source_runtime_version="1.3.6", baseline_version="1.3.6",
    )
    transport.try_emit(env.to_bytes())
    outcome = worker.run_once(timeout=0.05)
    result = {
        "phase": "8.3",
        "kill_switch": config.kill_switch_engaged,
        "outcome": outcome.status.value if outcome else None,
        "event_id": outcome.event_id if outcome else "",
        "reason": outcome.reason if outcome else "",
    }
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    print()
    # Kill switch ON => we expect SKIPPED/KILL_SWITCH, never a live run.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())