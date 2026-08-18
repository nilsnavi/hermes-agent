from __future__ import annotations
import json, os
import pytest
from tests.sandbox_runtime.conftest import make_request, write_text
from agent.sandbox_runtime.snapshot import SnapshotManager
from agent.sandbox_runtime.exceptions import BackupFailed


def _snap(root, txid="tx-a"):
    target=os.path.join(root.root,"data.txt"); write_text(target,"before")
    req=make_request(target="data.txt", expected_state="present")
    return SnapshotManager(root), SnapshotManager(root).create(txid,req,target), target


@pytest.mark.parametrize("damage", ["manifest_missing","content_missing","hash_mismatch","permissions_corrupt","wrong_txid","wrong_resource","truncated"])
def test_corrupted_snapshot_fails_closed(sandbox_root, damage):
    mgr,snap,target=_snap(sandbox_root)
    manifest=os.path.join(snap.dir,"manifest.json"); content=os.path.join(snap.dir,"target.bin")
    if damage=="manifest_missing": os.unlink(manifest)
    elif damage=="content_missing": os.unlink(content)
    elif damage=="hash_mismatch": open(content,"wb").write(b"corrupt")
    elif damage=="permissions_corrupt": open(os.path.join(snap.dir,"perms.json"),"w").write("{")
    elif damage=="wrong_txid":
        d=json.load(open(manifest)); d["transaction_id"]="tx-b"; open(manifest,"w").write(json.dumps(d))
    elif damage=="wrong_resource":
        d=json.load(open(manifest)); d["resource_fingerprint"]="bad"; open(manifest,"w").write(json.dumps(d))
    else: open(manifest,"w").write("{")
    assert not mgr.validate_for(snap,"tx-a",target)
    with pytest.raises(BackupFailed): mgr.restore(snap,target)


def test_cross_transaction_snapshot_reuse_denied(sandbox_root):
    mgr,snap,target=_snap(sandbox_root)
    assert mgr.validate_for(snap,"tx-a",target)
    assert not mgr.validate_for(snap,"tx-b",target)
