"""Sprint 1.3.16 tests — read-only recovery CLI + dry-run (no execute)."""
from __future__ import annotations

import subprocess
import sys

from agent.multi_service_recovery.cli import main


def test_cli_has_no_execute_or_mutate_commands():
    import inspect
    src = inspect.getsource(main)
    # only the six read-only, no-mutation subcommands are declared
    verbs = ["status", "inspect", "classify", "events", "compensation-plan", "dry-run"]
    for verb in verbs:
        assert verb in src
    # no execute / mutate subcommand, no --force flag
    assert '"execute"' not in src
    assert "--force" not in src
    assert "--mutate" not in src


def test_cli_requires_subcommand_fails_closed():
    # no subcommand -> argparse usage error; never auto-mutates.
    import pytest
    with pytest.raises(SystemExit) as ex:
        main([])
    assert ex.value.code != 0


def test_dry_run_does_not_mutate_store(tmp_path, monkeypatch):
    from agent.multi_service_recovery.clock import FixedClock
    from agent.multi_service_recovery.coordinator import MultiServiceRecoveryCoordinator
    from agent.multi_service_recovery.provenance import Provenance
    from tests.multi_service_recovery.conftest import make_store
    store = make_store(tmp_path)
    J = ["GLOBAL_CLAIMED", "SIMULATION_STARTED", "CHILD_SIMULATED",
         "CHILD_SIMULATED", "VERIFY_COMPLETED", "GLOBAL_SIMULATED_COMMIT"]
    prov = Provenance(host_identity=store.host_identity)
    coord = MultiServiceRecoveryCoordinator(store, provenance=prov,
                                            clock=FixedClock(5000),
                                            transaction_id="dry", semantic_key="dry",
                                            baseline_sha="b", plan_hash="p",
                                            graph_digest="g",
                                            service_set=("fake-aux-a", "fake-aux-b"),
                                            recovery_generation=1)
    plan = coord.recover(journal_types=J, child_states={},
                         idempotency_state="COMMITTED_SIMULATED")
    assert plan.disposition.value == "TERMINAL"
    assert coord.adapter_calls == 0