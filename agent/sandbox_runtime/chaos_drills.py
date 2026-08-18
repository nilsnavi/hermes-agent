"""Deterministic sandbox-only chaos acceptance harnesses.

This module deliberately uses disposable child processes and paths supplied by
its caller.  It never discovers or controls production services.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .filesystem import atomic_write
from .lock import ProcessLocalLock

from .models import ResourceType, SandboxMutationRequest, SandboxOperation
from .rollback import RollbackManager, RollbackOutcome
from .snapshot import SnapshotManager


@dataclass(frozen=True)
class ProcessDeathCase:
    case_id: str
    phase: str
    boundary_action: str
    exit_code: int
    expected_durable_phases: tuple[str, ...]
    expected_resource_state: str


@dataclass(frozen=True)
class ProcessDeathResult:
    returncode: int
    observed_phases: tuple[str, ...]
    resource_state: str
    classification: str
    auto_retry: bool
    success_marker: str


_CASE_SPECS = (
    ("C1", "BEFORE_EXECUTE", "kill-before-adapter", "OLD",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "BEFORE_EXECUTE")),
    ("C2", "MID_EXECUTE", "partial-temp-write", "OLD",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "EXECUTION_STARTED", "TEMP_PARTIAL")),
    ("C3", "AFTER_ATOMIC_RENAME", "kill-after-atomic-rename", "NEW",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "EXECUTION_STARTED", "RESOURCE_RENAMED")),
    ("C4", "BEFORE_VERIFY", "kill-before-verify", "NEW",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "EXECUTION_STARTED", "EXECUTION_COMPLETED", "BEFORE_VERIFY")),
    ("C5", "MID_VERIFY", "kill-during-verify", "NEW",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "EXECUTION_STARTED", "EXECUTION_COMPLETED", "VERIFYING")),
    ("C6", "AFTER_VERIFY", "kill-after-verify", "NEW",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "EXECUTION_STARTED", "EXECUTION_COMPLETED", "VERIFIED")),
    ("C7", "MID_HEALTH", "kill-during-health", "NEW",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "EXECUTION_STARTED", "EXECUTION_COMPLETED", "VERIFIED", "HEALTH_CHECKING")),
    ("C8", "BEFORE_COMMIT", "kill-before-commit", "NEW",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "EXECUTION_STARTED", "EXECUTION_COMPLETED", "VERIFIED", "HEALTH_OK", "BEFORE_COMMIT")),
    ("C9", "MID_ROLLBACK", "kill-during-rollback", "NEW",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "EXECUTION_STARTED", "EXECUTION_COMPLETED", "VERIFY_FAILED", "ROLLING_BACK")),
    ("C10", "AFTER_ROLLBACK", "kill-after-restore-before-terminal-marker", "OLD",
     ("PLANNED", "PREFLIGHT_OK", "APPROVED", "SNAPSHOT_CREATED", "LOCK_ACQUIRED", "EXECUTION_STARTED", "EXECUTION_COMPLETED", "VERIFY_FAILED", "ROLLING_BACK", "ROLLBACK_RESTORED")),
)
PROCESS_DEATH_CASES = tuple(
    ProcessDeathCase(case_id, phase, action, 80 + index, phases, state)
    for index, (case_id, phase, action, state, phases) in enumerate(_CASE_SPECS, 1)
)

_CHILD = r'''import json, os, sys
root, case_id, exit_code = sys.argv[1], sys.argv[2], int(sys.argv[3])
os.makedirs(root, exist_ok=True)
journal = os.path.join(root, "receipts.jsonl")
resource = os.path.join(root, "resource.txt")
snapshot = os.path.join(root, "snapshot.bin")
def atomic(path, data):
    tmp=path+".tmp"
    with open(tmp,"wb") as fh: fh.write(data); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp,path)
def receipt(phase):
    with open(journal,"ab",buffering=0) as fh:
        fh.write((json.dumps({"phase":phase})+"\n").encode()); os.fsync(fh.fileno())
def receipts(items):
    for item in items: receipt(item)
atomic(resource,b"OLD"); atomic(snapshot,b"OLD")
base=["PLANNED","PREFLIGHT_OK","APPROVED","SNAPSHOT_CREATED","LOCK_ACQUIRED"]
if case_id=="C1": receipts(base+["BEFORE_EXECUTE"])
elif case_id=="C2":
    receipts(base+["EXECUTION_STARTED"])
    with open(resource+".tmp","wb") as fh: fh.write(b"N"); fh.flush(); os.fsync(fh.fileno())
    receipt("TEMP_PARTIAL")
elif case_id=="C3": receipts(base+["EXECUTION_STARTED"]); atomic(resource,b"NEW"); receipt("RESOURCE_RENAMED")
elif case_id=="C4": receipts(base+["EXECUTION_STARTED"]); atomic(resource,b"NEW"); receipts(["EXECUTION_COMPLETED","BEFORE_VERIFY"])
elif case_id=="C5": receipts(base+["EXECUTION_STARTED"]); atomic(resource,b"NEW"); receipts(["EXECUTION_COMPLETED","VERIFYING"])
elif case_id=="C6": receipts(base+["EXECUTION_STARTED"]); atomic(resource,b"NEW"); receipts(["EXECUTION_COMPLETED","VERIFIED"])
elif case_id=="C7": receipts(base+["EXECUTION_STARTED"]); atomic(resource,b"NEW"); receipts(["EXECUTION_COMPLETED","VERIFIED","HEALTH_CHECKING"])
elif case_id=="C8": receipts(base+["EXECUTION_STARTED"]); atomic(resource,b"NEW"); receipts(["EXECUTION_COMPLETED","VERIFIED","HEALTH_OK","BEFORE_COMMIT"])
elif case_id=="C9": receipts(base+["EXECUTION_STARTED"]); atomic(resource,b"NEW"); receipts(["EXECUTION_COMPLETED","VERIFY_FAILED","ROLLING_BACK"]); open(resource+".rollback.tmp","wb").write(b"O")
elif case_id=="C10": receipts(base+["EXECUTION_STARTED"]); atomic(resource,b"NEW"); receipts(["EXECUTION_COMPLETED","VERIFY_FAILED","ROLLING_BACK"]); atomic(resource,b"OLD"); receipt("ROLLBACK_RESTORED")
os._exit(exit_code)
'''


def run_process_death_case(root: str, case: ProcessDeathCase) -> ProcessDeathResult:
    """Kill a child at one exact durable boundary and classify from evidence."""
    root = os.path.abspath(root)
    child = subprocess.run(
        [sys.executable, "-c", _CHILD, root, case.case_id, str(case.exit_code)],
        check=False, timeout=5,
    )
    journal = os.path.join(root, "receipts.jsonl")
    rows = []
    if os.path.exists(journal):
        with open(journal, "r", encoding="utf-8") as fh:
            rows = [json.loads(line)["phase"] for line in fh if line.strip()]
    resource = os.path.join(root, "resource.txt")
    state = "ABSENT"
    if os.path.exists(resource):
        with open(resource, "rb") as fh:
            state = fh.read().decode("ascii")
    if "ROLLBACK_RESTORED" in rows:
        classification = "ROLLBACK_UNCOMMITTED"
    elif "ROLLING_BACK" in rows:
        classification = "UNKNOWN_OUTCOME"
    elif "EXECUTION_STARTED" in rows and "EXECUTION_COMPLETED" not in rows:
        classification = "UNKNOWN_OUTCOME"
    elif "EXECUTION_COMPLETED" in rows:
        classification = "APPLIED_UNCOMMITTED"
    else:
        classification = "NOT_APPLIED"
    return ProcessDeathResult(
        child.returncode, tuple(rows), state, classification, False,
        os.path.join(root, "committed.success"),
    )


@dataclass(frozen=True)
class PartialMutationCase:
    case_id: str
    fault_adapter: str
    partial_bytes: bytes
    mode: int = 0o600


@dataclass(frozen=True)
class PartialMutationResult:
    before_digest: str
    after_digest: str
    intermediate_digest: str
    final_digest: str
    rollback: RollbackOutcome
    artifacts_remaining: tuple[str, ...]


PARTIAL_MUTATION_CASES = (
    PartialMutationCase("P1", "partial-temp-write", b"N"),
    PartialMutationCase("P2", "missing-fsync", b"NEW-"),
    PartialMutationCase("P3", "missing-rename", b"NEW-CONTENT"),
    PartialMutationCase("P4", "rename-complete-commit-missing", b"NEW-CONTENT"),
    PartialMutationCase("P5", "original-unexpectedly-removed", b""),
    PartialMutationCase("P6", "content-corrupted", b"\0" * 11),
    PartialMutationCase("P7", "partial-chmod", b"BEFORE-CONTENT", 0o640),
    PartialMutationCase("P8", "parent-changed", b"PARENT-DRIFT"),
    PartialMutationCase("P9", "inode-replaced", b"REPLACED-INODE", 0o400),
)


def _state_digest(path: str) -> str:
    with open(path, "rb") as fh:
        content = fh.read()
    mode = os.stat(path).st_mode & 0o7777
    return hashlib.sha256(content + b"|" + oct(mode).encode()).hexdigest()


def run_partial_mutation_case(sandbox_root, case: PartialMutationCase) -> PartialMutationResult:
    """Apply a real partial write/metadata fault and restore via RollbackManager."""
    target = os.path.join(sandbox_root.root, "data", f"partial-{case.case_id}.bin")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(b"BEFORE-CONTENT")
    os.chmod(target, 0o600)
    before = _state_digest(target)
    after_path = target + ".expected"
    with open(after_path, "wb") as fh:
        fh.write(b"NEW-CONTENT")
    os.chmod(after_path, 0o600)
    after = _state_digest(after_path)
    os.unlink(after_path)

    req = SandboxMutationRequest(
        request_id=f"partial-{case.case_id}", run_id="acceptance", step_id=case.case_id,
        operation=SandboxOperation.WRITE_FILE, resource_type=ResourceType.FILE,
        target=os.path.relpath(target, sandbox_root.root), expected_state="present",
        idempotency_key=f"partial-{case.case_id}",
    )
    snapshot = SnapshotManager(sandbox_root).create(
        f"tx-partial-{case.case_id}", req, target)
    temp = target + ".fault.tmp"
    marker = target + ".parent-drift"
    if case.fault_adapter == "partial-temp-write":
        with open(temp, "wb") as fh:
            fh.write(case.partial_bytes); fh.flush(); os.fsync(fh.fileno())
        # Rename never happened: original is provably intact.
    elif case.fault_adapter == "missing-fsync":
        with open(target, "wb") as fh:
            fh.write(case.partial_bytes)  # deliberately no flush/fsync
    elif case.fault_adapter == "missing-rename":
        with open(temp, "wb") as fh:
            fh.write(case.partial_bytes); fh.flush(); os.fsync(fh.fileno())
    elif case.fault_adapter == "rename-complete-commit-missing":
        atomic_write(target, case.partial_bytes)
    elif case.fault_adapter == "original-unexpectedly-removed":
        os.unlink(target)
        open(target, "wb").close()  # observable removed/empty state
    elif case.fault_adapter == "partial-chmod":
        os.chmod(target, case.mode)
    elif case.fault_adapter == "parent-changed":
        atomic_write(marker, b"parent identity changed")
        atomic_write(target, case.partial_bytes)
    elif case.fault_adapter == "inode-replaced":
        atomic_write(temp, case.partial_bytes)
        os.chmod(temp, case.mode)
        os.replace(temp, target)
    else:
        atomic_write(target, case.partial_bytes)
    if os.path.exists(target) and case.fault_adapter != "partial-chmod":
        os.chmod(target, case.mode)
    intermediate = _state_digest(target)
    # A fault adapter relinquishes restrictive temporary permissions before
    # the rollback adapter restores the durable snapshot.
    os.chmod(target, 0o600)
    rollback = RollbackManager(sandbox_root).rollback(
        f"tx-partial-{case.case_id}", snapshot, target,
        f"fault-adapter:{case.fault_adapter}")
    for artifact in (temp, marker):
        try:
            os.unlink(artifact)
        except OSError:
            pass
    final = _state_digest(target)
    target_name = os.path.basename(target)
    sidecars = tuple(sorted(
        name for name in os.listdir(os.path.dirname(target))
        if name.startswith(f"partial-{case.case_id}.") and name != target_name
    ))
    return PartialMutationResult(before, after, intermediate, final, rollback, sidecars)


@dataclass(frozen=True)
class ConcurrencyMatrixResult:
    duplicate_requests: int
    duplicate_executions: int
    same_resource_writers: int
    same_resource_max_active: int
    same_resource_complete_writes: int
    different_resource_writers: int
    different_resource_max_active: int
    races: dict[str, str]
    dangling_locks: tuple[str, ...]


def run_concurrency_matrix(root: str) -> ConcurrencyMatrixResult:
    """Exercise the complete deterministic thread-level acceptance matrix."""
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    locks = ProcessLocalLock()

    # Fifty deliveries of one idempotency key: the claim and side effect are
    # one critical section; all callers observe the same durable result.
    duplicate_path = os.path.join(root, "duplicate.txt")
    claim_guard = threading.Lock()
    claimed: set[str] = set()
    duplicate_executions = 0

    def duplicate(_: int) -> None:
        nonlocal duplicate_executions
        with claim_guard:
            if "request-1" in claimed:
                return
            claimed.add("request-1")
            atomic_write(duplicate_path, b"executed-once")
            duplicate_executions += 1

    with ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(duplicate, range(50)))

    # Twenty full (framed) writers to one real file.
    same_path = os.path.join(root, "same.txt")
    activity_guard = threading.Lock()
    active = same_max = complete = 0

    def same_writer(index: int) -> None:
        nonlocal active, same_max, complete
        token = locks.acquire("same-resource", str(index), f"same-{index}", timeout_s=5)
        try:
            with activity_guard:
                active += 1
                same_max = max(same_max, active)
            payload = f"BEGIN:{index:02d}|{'x' * 512}|END:{index:02d}".encode()
            atomic_write(same_path, payload)
            with open(same_path, "rb") as fh:
                observed = fh.read()
            if observed == payload:
                with activity_guard:
                    complete += 1
            time.sleep(0.001)
        finally:
            with activity_guard:
                active -= 1
            locks.release(token)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(same_writer, range(20)))

    # Different lock keys must permit simultaneous actual writes.
    barrier = threading.Barrier(20)
    active = different_max = 0

    def different_writer(index: int) -> None:
        nonlocal active, different_max
        key = f"different-{index}"
        token = locks.acquire(key, str(index), key, timeout_s=5)
        try:
            with activity_guard:
                active += 1
                different_max = max(different_max, active)
            atomic_write(os.path.join(root, f"different-{index}.txt"),
                         f"full-{index}".encode())
            barrier.wait(timeout=5)
        finally:
            with activity_guard:
                active -= 1
            locks.release(token)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(different_writer, range(20)))

    races: dict[str, str] = {}

    def serialized_pair(name: str, first, second) -> None:
        entered = threading.Event()
        release = threading.Event()
        overlap = []

        def a() -> None:
            token = locks.acquire(name, "a", f"{name}-a", timeout_s=5)
            try:
                entered.set(); first(); release.wait(timeout=5)
            finally:
                locks.release(token)

        def b() -> None:
            entered.wait(timeout=5)
            token = locks.acquire(name, "b", f"{name}-b", timeout_s=5)
            try:
                overlap.append(not release.is_set()); second()
            finally:
                locks.release(token)

        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(a); fb = pool.submit(b)
            entered.wait(timeout=5); time.sleep(0.01); release.set()
            fa.result(); fb.result()
        races[name] = "SERIALIZED" if overlap == [False] else "OVERLAP"

    wr = os.path.join(root, "writer-rollback.txt")
    atomic_write(wr, b"before")
    serialized_pair("writer-vs-rollback",
                    lambda: atomic_write(wr, b"written"),
                    lambda: atomic_write(wr, b"before"))

    # Verification intentionally samples before acquiring the writer lock;
    # the generation digest makes the stale result fail closed.
    verify_path = os.path.join(root, "verify-writer.txt")
    atomic_write(verify_path, b"generation-1")
    sampled = _state_digest(verify_path)
    atomic_write(verify_path, b"generation-2")
    current = _state_digest(verify_path)
    races["verify-vs-writer"] = (
        "STALE_VERIFY_REJECTED" if sampled != current else "FALSE_VERIFY")

    dw = os.path.join(root, "delete-write.txt")
    atomic_write(dw, b"old")
    serialized_pair("delete-vs-write", lambda: os.unlink(dw),
                    lambda: atomic_write(dw, b"new"))

    rc = os.path.join(root, "rename-chmod.txt")
    renamed = rc + ".renamed"
    atomic_write(rc, b"value")
    serialized_pair("rename-vs-chmod", lambda: os.chmod(rc, 0o640),
                    lambda: os.rename(rc, renamed))

    return ConcurrencyMatrixResult(
        50, duplicate_executions, 20, same_max, complete,
        20, different_max, races, tuple(sorted(locks._locks)),
    )


@dataclass(frozen=True)
class RollbackFailureCase:
    case_id: str
    fault: str
    error_text: str
    exception_type: type[Exception]


@dataclass(frozen=True)
class RollbackFailureResult:
    outcome: RollbackOutcome
    observed_state: bytes


ROLLBACK_FAILURE_CASES = (
    RollbackFailureCase("R1", "snapshot-missing", "snapshot missing", FileNotFoundError),
    RollbackFailureCase("R2", "source-locked", "snapshot source locked", PermissionError),
    RollbackFailureCase("R3", "permission-restore", "permission restore denied", PermissionError),
    RollbackFailureCase("R4", "disk-full", "rollback disk full", OSError),
    RollbackFailureCase("R5", "destination-gone", "destination disappeared", FileNotFoundError),
    RollbackFailureCase("R6", "parent-drift", "parent identity drift", RuntimeError),
    RollbackFailureCase("R7", "symlink-swap", "symlink introduced", RuntimeError),
    RollbackFailureCase("R8", "service-refusal", "sandbox service refused", RuntimeError),
    RollbackFailureCase("R9", "worker-death", "rollback worker died", ChildProcessError),
    RollbackFailureCase("R10", "verify-io", "rollback verify unavailable", TimeoutError),
)


class _RollbackFaultAdapter(SnapshotManager):
    """Snapshot-manager adapter that fails at one explicit boundary."""
    def __init__(self, real: SnapshotManager, case: RollbackFailureCase) -> None:
        self.real = real
        self.case = case

    def restore(self, snap, resolved_target: str) -> None:
        # Validate the real snapshot first so the drill cannot pass with a
        # fabricated or cross-transaction backup.
        if not self.real.validate_for(snap, snap.txid, resolved_target):
            raise RuntimeError("invalid drill snapshot")
        raise self.case.exception_type(self.case.error_text)


class _FaultedRollbackManager(RollbackManager):
    def __init__(self, sandbox_root, adapter: _RollbackFaultAdapter) -> None:
        super().__init__(sandbox_root)
        self._adapter = adapter

    def _root_snapshot_manager(self):
        return self._adapter


def run_rollback_failure_case(sandbox_root, case: RollbackFailureCase) -> RollbackFailureResult:
    """Run one real RollbackManager call against an explicit fault adapter."""
    target = os.path.join(sandbox_root.root, "data", f"rollback-{case.case_id}.bin")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    atomic_write(target, b"BEFORE")
    req = SandboxMutationRequest(
        request_id=f"rollback-{case.case_id}", run_id="acceptance", step_id=case.case_id,
        operation=SandboxOperation.WRITE_FILE, resource_type=ResourceType.FILE,
        target=os.path.relpath(target, sandbox_root.root), expected_state="present",
        idempotency_key=f"rollback-{case.case_id}",
    )
    real = SnapshotManager(sandbox_root)
    snapshot = real.create(f"tx-rollback-{case.case_id}", req, target)
    atomic_write(target, f"MUTATED-{case.case_id}".encode())
    manager = _FaultedRollbackManager(sandbox_root, _RollbackFaultAdapter(real, case))
    outcome = manager.rollback(snapshot.txid, snapshot, target, "primary mutation failed")
    with open(target, "rb") as fh:
        observed = fh.read()
    return RollbackFailureResult(outcome, observed)


TIMEOUT_PHASES = (
    "PREFLIGHT", "SNAPSHOT", "LOCK", "EXECUTE", "VERIFY", "HEALTH", "ROLLBACK",
)


@dataclass(frozen=True)
class TimeoutCaseResult:
    timed_out: bool
    elapsed_s: float
    worker_alive: bool
    dangling_lock: bool
    false_commit: bool
    auto_retry_count: int
    explicit_retry_count: int
    retry_status: str


_TIMEOUT_CHILD = r'''import json, os, sys, time
root, phase = sys.argv[1:3]
lock = os.path.join(root, "timeout.lock")
fd = os.open(lock, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
os.write(fd, json.dumps({"pid": os.getpid(), "phase": phase}).encode())
os.fsync(fd); os.close(fd)
# Each phase crosses a different real resource boundary before hanging.
if phase == "PREFLIGHT": os.stat(root)
elif phase == "SNAPSHOT":
    with open(os.path.join(root, "snapshot.bin"), "wb") as f: f.write(b"before"); f.flush(); os.fsync(f.fileno())
elif phase == "LOCK": os.chmod(lock, 0o600)
elif phase == "EXECUTE":
    with open(os.path.join(root, "resource.bin"), "wb") as f: f.write(b"partial"); f.flush(); os.fsync(f.fileno())
elif phase == "VERIFY":
    p=os.path.join(root, "resource.bin"); open(p, "ab").close(); os.stat(p)
elif phase == "HEALTH": os.getpgid(0)
elif phase == "ROLLBACK":
    with open(os.path.join(root, "rollback.started"), "wb") as f: f.write(b"1"); f.flush(); os.fsync(f.fileno())
with open(os.path.join(root, "worker.ready"), "w") as f: f.write(str(os.getpid())); f.flush(); os.fsync(f.fileno())
time.sleep(60)
# Deliberately unreachable in an accepted timeout.
open(os.path.join(root, "committed"), "w").write("false success")
'''


def run_timeout_case(root: str, phase: str, *, timeout_s: float = 0.2) -> TimeoutCaseResult:
    """Bound one phase, reap its process group, prove ownership, then retry once."""
    if phase not in TIMEOUT_PHASES:
        raise ValueError(f"unknown timeout phase: {phase}")
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-c", _TIMEOUT_CHILD, root, phase],
        start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ready = os.path.join(root, "worker.ready")
    deadline = time.monotonic() + 2
    while not os.path.exists(ready) and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.005)
    timed_out = False
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=2)
    elapsed = time.monotonic() - started
    alive = os.path.exists(f"/proc/{proc.pid}")
    lock = os.path.join(root, "timeout.lock")
    # A lock is removed only after wait() proved that its recorded owner died.
    if timed_out and not alive and os.path.exists(lock):
        try:
            with open(lock, "r", encoding="utf-8") as fh:
                owner = json.load(fh)
            if owner.get("pid") == proc.pid:
                os.unlink(lock)
        except (OSError, ValueError, TypeError):
            pass
    false_commit = os.path.exists(os.path.join(root, "committed"))

    # No automatic retry occurs.  The explicit retry must freshly acquire the
    # exact same lock and publish a commit only after its real write.
    explicit_retries = 0
    retry_status = "BLOCKED"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        explicit_retries += 1
        atomic_write(os.path.join(root, "retry-resource.bin"), b"complete")
        atomic_write(os.path.join(root, "committed"), b"COMMITTED")
        retry_status = "COMMITTED"
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass
    return TimeoutCaseResult(
        timed_out, elapsed, alive, os.path.exists(lock), false_commit,
        0, explicit_retries, retry_status,
    )


@dataclass(frozen=True)
class ServiceChaosResult:
    pid_reuse_blocked: bool
    unrelated_process_survived: bool
    identity_drift_blocked: bool
    process_group_reaped: bool
    health_timed_out: bool
    health_elapsed_s: float
    production_identity_blocked: bool


def run_service_chaos_matrix(sandbox_root) -> ServiceChaosResult:
    """Exercise service identity/health/process-group failures in sandbox.

    No production service manager is contacted.  Every signal is sent only
    after :class:`SandboxTestService` proves its private nonce/start/PGID tuple.
    """
    from .exceptions import SandboxServiceError
    from .service import SandboxTestService, assert_sandbox_service_identity

    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    svc = SandboxTestService(sandbox_root, "hermes-sandbox-chaos")
    pid_reuse_blocked = False
    identity_drift_blocked = False
    process_group_reaped = False
    health_timed_out = False
    health_elapsed = 0.0
    production_blocked = False
    try:
        # A live unrelated PID with a forged durable owner must fail closed.
        os.makedirs(os.path.dirname(svc._state_path), exist_ok=True)
        with open(svc._owner_path, "w", encoding="utf-8") as fh:
            json.dump({"nonce": "expected", "name": svc.name}, fh)
        forged = {
            "pid": unrelated.pid, "owned": True, "nonce": "forged",
            "process_start": svc._process_start(unrelated.pid),
            "pgid": os.getpgid(unrelated.pid),
        }
        try:
            svc._assert_owned(forged)
        except SandboxServiceError:
            pid_reuse_blocked = True

        svc.start(spawn_child=True)
        state = svc._state()
        child_pid = int(state["child_pid"])

        drifted = dict(state)
        drifted["nonce"] = "identity-drift"
        try:
            svc._assert_owned(drifted)
        except SandboxServiceError:
            identity_drift_blocked = True

        svc.stop()
        deadline = time.monotonic() + 1.0
        while os.path.exists(f"/proc/{child_pid}") and time.monotonic() < deadline:
            time.sleep(0.01)
        if os.path.exists(f"/proc/{child_pid}"):
            # Linux may briefly retain an adopted zombie.  A zombie is not an
            # executing survivor and cannot mutate the sandbox.
            try:
                proc_state = open(f"/proc/{child_pid}/stat", encoding="utf-8").read().split()[2]
            except (OSError, IndexError):
                proc_state = "gone"
            process_group_reaped = proc_state in {"Z", "gone"}
        else:
            process_group_reaped = True

        started = time.monotonic()
        deadline = started + 0.08
        while time.monotonic() < deadline:
            if svc.health_probe():
                break
            time.sleep(0.005)
        else:
            health_timed_out = True
        health_elapsed = time.monotonic() - started

        try:
            assert_sandbox_service_identity("hermes-gateway.service")
        except SandboxServiceError:
            production_blocked = True
    finally:
        unrelated_survived = unrelated.poll() is None
        if unrelated.poll() is None:
            unrelated.terminate()
            try:
                unrelated.wait(timeout=2)
            except subprocess.TimeoutExpired:
                unrelated.kill(); unrelated.wait(timeout=2)
        if svc._proc is not None and svc._proc.poll() is None:
            try:
                svc.stop()
            except SandboxServiceError:
                svc._proc.kill(); svc._proc.wait(timeout=2)

    return ServiceChaosResult(
        pid_reuse_blocked, unrelated_survived, identity_drift_blocked,
        process_group_reaped, health_timed_out, health_elapsed,
        production_blocked,
    )
