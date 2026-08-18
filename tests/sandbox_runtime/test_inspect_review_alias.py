"""Sprint 1.3.6.1 CLI alias: inspect-review must mirror manual-reviews <id>."""
from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout

from agent.sandbox_runtime.cli import main as cli_main
from agent.sandbox_runtime.manual_review import ManualReviewStore


def _create_review(sandbox_root, **overrides) -> str:
    store = ManualReviewStore(sandbox_root)
    item = store.create(
        transaction_id=overrides.get("transaction_id", "tx-cli"),
        reason=overrides.get("reason", "smoke"),
        resource=overrides.get("resource", "data/secret=masked"),
        operation=overrides.get("operation", "WRITE_FILE"),
        state_observed=overrides.get("state_observed", "partial"),
        state_expected=overrides.get("state_expected", "after"),
        original_error=overrides.get("original_error", "token=REDACTED"),
        rollback_error=overrides.get("rollback_error", None),
    )
    return item.review_id


def _capture_stdout(fn) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn()
    return buf.getvalue()


def test_inspect_review_alias_matches_manual_reviews_id(sandbox_root):
    review_id = _create_review(sandbox_root)

    out_a = _capture_stdout(
        lambda: cli_main(["--root", sandbox_root.root, "manual-reviews", review_id])
    )
    out_b = _capture_stdout(
        lambda: cli_main(["--root", sandbox_root.root, "inspect-review", review_id])
    )

    payload_a = json.loads(out_a)
    payload_b = json.loads(out_b)
    assert payload_a == payload_b
    assert payload_b[0]["review_id"] == review_id


def test_inspect_review_is_read_only(sandbox_root):
    review_id = _create_review(sandbox_root)
    store = ManualReviewStore(sandbox_root)
    file_path = store._file
    before = open(file_path, "rb").read()
    mtime_before = os.stat(file_path).st_mtime_ns

    out = _capture_stdout(
        lambda: cli_main(["--root", sandbox_root.root, "inspect-review", review_id])
    )
    payload = json.loads(out)
    assert payload[0]["review_id"] == review_id

    assert open(file_path, "rb").read() == before
    assert os.stat(file_path).st_mtime_ns == mtime_before


def test_inspect_review_unknown_id_fails_cleanly(sandbox_root, capsys):
    rc = cli_main([
        "--root", sandbox_root.root, "inspect-review",
        "00000000-0000-0000-0000-000000000000",
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err.strip()
    assert "not found" in captured.err


def test_inspect_review_no_secret_leak(sandbox_root):
    review_id = _create_review(
        sandbox_root,
        reason="Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
        resource="data/api_key=ABCDEFGHIJKLMNOPQRSTUV",
        original_error="cookie=abcdef0123456789",
    )
    out = _capture_stdout(
        lambda: cli_main(["--root", sandbox_root.root, "inspect-review", review_id])
    )
    lowered = out.lower()
    assert "abcdefghijklmnopqrstuvwxyz012345" not in lowered
    assert "abcdef0123456789" not in lowered
    assert "[redacted]" in lowered
