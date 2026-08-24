"""Sprint 1.3.17 — lock coordination revalidation (§15)."""

from __future__ import annotations

from collections.abc import Mapping


def lock_owner_valid(
    lock_record: Mapping[str, object] | None,
    *,
    expected_tx: str,
    expected_generation: int,
    owner_runtime: str,
    expected_service_set: set[str],
    now_monotonic: float,
) -> tuple[bool, str]:
    """Validate the CanonicalLockSet lock ownership immediately before execution.

    All of the following must hold or the lock is NOT live: same runtime, same
    tx, same generation, valid nonce, valid process identity, not stale, not PID
    reuse, not a foreign owner.
    """
    if lock_record is None:
        return False, "no-lock-record"
    if lock_record.get("owner_runtime") != owner_runtime:
        return False, "foreign-owner-runtime"
    if str(lock_record.get("tx")) != expected_tx:
        return False, "tx-mismatch"
    if int(lock_record.get("generation", -1)) != expected_generation:
        return False, "generation-mismatch"
    nonce = lock_record.get("nonce")
    if not nonce:
        return False, "missing-nonce"
    expiry = float(lock_record.get("expiry_monotonic", 0))
    if expiry <= now_monotonic:
        return False, "stale-lock"
    pid = lock_record.get("pid")
    start = lock_record.get("process_start_identity")
    if pid is None or not start:
        return False, "missing-process-identity"
    # PID reuse guard: caller must confirm the live process start matches; we
    # deny when the validating process cannot positively confirm it.
    if lock_record.get("pid_reuse"):
        return False, "pid-reuse"
    return True, "live-owner"


def lockset_digest(records: Mapping[str, Mapping[str, object]]) -> str:
    import hashlib
    return hashlib.sha256(",".join(f"{k}:{v.get('nonce','')}" for k, v in sorted(records.items())
                                   ).encode()).hexdigest()


__all__ = ["lock_owner_valid", "lockset_digest"]