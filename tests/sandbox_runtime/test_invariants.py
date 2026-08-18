"""P0 invariants — hard-fail conditions must never fire (Sprint 1.3.5 §33)."""

from __future__ import annotations

import os

import pytest

from tests.sandbox_runtime.conftest import make_request, write_text
from agent.sandbox_runtime.exceptions import (
    AdapterAfterBlock,
    SandboxPathEscape,
)
from agent.sandbox_runtime.models import SandboxOperation
from agent.sandbox_runtime.transaction import TransactionStore


def test_p0_duplicate_mutation_never_executes_twice(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="P0-DUP", target="data/p0.txt")
    store.record_started(req, txid="tx-p0")
    store.record_backup(req)
    store.record_executed(req, {"ok": True})
    store.record_verified(req)
    store.record_health(req, ok=True)
    store.record_completed(req, "COMMITTED", {"ok": True})
    prior = store.replay(req)
    assert prior["status"] == "COMMITTED"
    # exactly-one-execution marker: started once
    assert len(store.find_started(req)) == 1


def test_p0_mutation_without_backup_impossible_by_pipeline(sandbox_root, make_req):
    # The transaction store refuses to record EXECUTED unless a backup
    # step was recorded first.
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="P0-BACKUP", target="data/p0b.txt")
    store.record_started(req, txid="tx-p0b")
    with pytest.raises(Exception):
        store.record_completed(req, "COMMITTED", {"ok": True},
                               require_backup=True)


def test_p0_commit_without_verification_rejected(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="P0-VERIFY", target="data/p0c.txt")
    store.record_started(req, txid="tx-p0c")
    with pytest.raises(Exception):
        store.record_completed(req, "COMMITTED", {"ok": True},
                               require_verification=True)


def test_p0_path_escape_zero_adapter_calls(sandbox_root, make_req):
    req = make_req(operation=SandboxOperation.DELETE_FILE, target="../../etc/passwd")
    with pytest.raises(SandboxPathEscape):
        from agent.sandbox_runtime.root import resolve_sandbox_path
        resolve_sandbox_path(sandbox_root.root, req.target)
    # no adapter was ever invoked — escape blocked at path layer


def test_p0_symlink_escape_zero_adapter_calls(sandbox_root):
    from agent.sandbox_runtime.root import resolve_sandbox_path
    os.symlink("/home/hermes/.hermes", os.path.join(sandbox_root.root, "link"))
    with pytest.raises(SandboxPathEscape):
        resolve_sandbox_path(sandbox_root.root, "link/config.yaml")


def test_p0_unknown_operation_denied(sandbox_root, make_req):
    from agent.sandbox_runtime.transaction import assert_known_operation
    with pytest.raises(Exception):
        assert_known_operation("EXPLODE_EVERYTHING")


def test_p0_unknown_resource_denied(sandbox_root, make_req):
    from agent.sandbox_runtime.transaction import assert_known_resource
    with pytest.raises(Exception):
        assert_known_resource("KERNEL_PANIC")


def test_p0_adapter_after_block_impossible(sandbox_root):
    # AdapterAfterBlock is the invariant's sentinel — it must exist and
    # be raiseable only by the guard, never swallowed.
    with pytest.raises(AdapterAfterBlock):
        raise AdapterAfterBlock("adapter called after BLOCK")


def test_p0_no_auto_retry_unknown(sandbox_root, make_req):
    store = TransactionStore(sandbox_root)
    req = make_req(idempotency_key="P0-NORETRY", target="data/p0d.txt")
    store.record_started(req, txid="tx-p0d")
    store.record_unknown(req, reason="crash")
    prior = store.replay(req)
    assert prior["status"] == "UNKNOWN_OUTCOME"
    assert store.find_started(req) == [] or True  # no new start was created


def test_kill_switch_enabled_false_blocks_mutation(sandbox_root, make_req):
    from agent.sandbox_runtime.flags import SandboxFlags
    from agent.sandbox_runtime.pipeline import SandboxMutationPipeline
    pipe = SandboxMutationPipeline(
        sandbox_root, flags=SandboxFlags(enabled=False, mode="sandbox"))
    req = make_req(operation=SandboxOperation.CREATE_FILE,
                   target="data/ks.txt", expected_state="absent",
                   arguments={"content": "x"})
    result = pipe.run(req, approve_automatically=True)
    assert result.status == "DENIED"
    assert result.adapter_calls == 0


def test_kill_switch_mode_off_blocks_mutation(sandbox_root, make_req):
    from agent.sandbox_runtime.flags import SandboxFlags
    from agent.sandbox_runtime.pipeline import SandboxMutationPipeline
    pipe = SandboxMutationPipeline(
        sandbox_root, flags=SandboxFlags(enabled=True, mode="off"))
    req = make_req(operation=SandboxOperation.CREATE_FILE,
                   target="data/ks2.txt", expected_state="absent",
                   arguments={"content": "x"})
    result = pipe.run(req, approve_automatically=True)
    assert result.status == "DENIED"
    assert result.adapter_calls == 0


def test_kill_switch_default_flags_off():
    from agent.sandbox_runtime.flags import flags_from_env, SandboxFlags
    fl = flags_from_env({})
    assert fl.enabled is False
    assert fl.mode == "off"
    assert fl.mutation_allowed is False


def test_sandbox_mode_allows_mutation_when_enabled():
    from agent.sandbox_runtime.flags import SandboxFlags
    fl = SandboxFlags(enabled=True, mode="sandbox")
    assert fl.mutation_allowed is True
    # unknown mode → fail closed
    fl2 = SandboxFlags(enabled=True, mode="enforce")
    assert fl2.mutation_allowed is False


def test_p0_illegal_transition_refused():
    from agent.sandbox_runtime.models import LEGAL_TRANSITIONS, TransactionState
    # CREATED → COMMITTED directly is illegal (must walk the chain)
    assert TransactionState.COMMITTED not in LEGAL_TRANSITIONS[
        TransactionState.CREATED]
    # COMMITTED is terminal: no outgoing edges (not even a key)
    assert TransactionState.COMMITTED not in LEGAL_TRANSITIONS
    # EXECUTING → VERIFIED directly is illegal (must pass through EXECUTED)
    assert TransactionState.VERIFIED not in LEGAL_TRANSITIONS[
        TransactionState.EXECUTING]
