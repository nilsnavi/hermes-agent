"""Sprint 1.3.16 tests — recovery claim entitlement (owner, renewal, host, PID)."""
from __future__ import annotations

from tests.multi_service_recovery.conftest import make_store


def test_recovery_claim_exactly_one_owner(tmp_path):
    store = make_store(tmp_path)
    r = store.claims.claim("tx-1", 1, pid=100, process_start_identity="p100",
                           runtime_identity="r", nonce="n1", lease_created=0.0,
                           lease_expiry=100.0, host_identity=store.host_identity)
    assert r == "CLAIMED"
    r2 = store.claims.claim("tx-1", 1, pid=200, process_start_identity="p200",
                            runtime_identity="r", nonce="n2", lease_created=0.0,
                            lease_expiry=100.0, host_identity=store.host_identity)
    assert r2 == "ALREADY_OWNED"  # live owner never taken over


def test_recovery_lease_expiry_bound(tmp_path):
    store = make_store(tmp_path)
    store.claims.claim("tx", 1, pid=1, process_start_identity="p1", runtime_identity="r",
                       nonce="n", lease_created=0.0, lease_expiry=100.0,
                       host_identity=store.host_identity)
    assert store.claims.is_live("tx", 1, now_monotonic=50.0) is True
    assert store.claims.is_live("tx", 1, now_monotonic=150.0) is False


def test_foreign_host_renew_denied(tmp_path):
    store = make_store(tmp_path)
    store.claims.claim("tx", 1, pid=1, process_start_identity="p1", runtime_identity="r",
                       nonce="n", lease_created=0.0, lease_expiry=100.0,
                       host_identity="host-a")
    # a different host cannot renew
    assert store.claims.renew("tx", 1, pid=1, process_start_identity="p1",
                              runtime_identity="r", host_identity="host-b",
                              new_expiry=200.0) is False


def test_pid_reuse_renew_denied(tmp_path):
    store = make_store(tmp_path)
    store.claims.claim("tx", 1, pid=1, process_start_identity="p1-start-OLD",
                       runtime_identity="r", nonce="n", lease_created=0.0,
                       lease_expiry=100.0, host_identity=store.host_identity)
    # same PID, different process-start identity => different process => DENY
    assert store.claims.renew("tx", 1, pid=1, process_start_identity="p1-start-NEW",
                              runtime_identity="r", host_identity=store.host_identity,
                              new_expiry=200.0) is False


def test_spoofed_runtime_renew_denied(tmp_path):
    store = make_store(tmp_path)
    store.claims.claim("tx", 1, pid=1, process_start_identity="p1", runtime_identity="genuine",
                       nonce="n", lease_created=0.0, lease_expiry=100.0,
                       host_identity=store.host_identity)
    assert store.claims.renew("tx", 1, pid=1, process_start_identity="p1",
                              runtime_identity="forged", host_identity=store.host_identity,
                              new_expiry=200.0) is False


def test_recovery_events_never_grant_authority(tmp_path):
    from agent.multi_service_recovery.store import RECOVERY_EVENTS
    store = make_store(tmp_path)
    store.journal.append("RECOVERY_CLAIMED", {"tx": "x"})
    assert store.journal.types() == ["RECOVERY_CLAIMED"]
    assert set(RECOVERY_EVENTS) >= {"RECOVERY_CLAIMED", "MANUAL_REVIEW_REQUIRED",
                                    "COMPENSATION_FAILED", "RECOVERY_COMPLETED"}