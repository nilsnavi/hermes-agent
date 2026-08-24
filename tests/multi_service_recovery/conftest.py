"""Shared fixtures for Sprint 1.3.16 recovery tests."""
from __future__ import annotations

from agent.multi_service_recovery.store import RecoveryStore

HOST = "host-a"
Runtime = "multi-service-recovery"


def make_store(tmp_path, host: str = HOST) -> RecoveryStore:
    return RecoveryStore(tmp_path / "recovery", host_identity=host)


def make_coordinator(store, *, tx_id="tx-1", generation=1, baseline="base-sha",
                     clock=None, prov_host=None):
    from agent.multi_service_recovery.coordinator import MultiServiceRecoveryCoordinator
    from agent.multi_service_recovery.provenance import Provenance
    from agent.multi_service_recovery.clock import FixedClock
    if clock is None:
        clock = FixedClock(5000.0)
    prov = Provenance(host_identity=prov_host or store.host_identity,
                      runtime_identity=Runtime)
    return MultiServiceRecoveryCoordinator(
        store, provenance=prov, clock=clock,
        transaction_id=tx_id, semantic_key=tx_id,
        baseline_sha=baseline, plan_hash="ph", graph_digest="gd",
        service_set=("fake-aux-a", "fake-aux-b"), recovery_generation=generation,
    )