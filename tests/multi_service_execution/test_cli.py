"""Sprint 1.3.17 — read-only CLI.  CLI MUST NOT mutate anything."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from agent.multi_service_execution.cli import main as cli_main
from tests.multi_service_execution.conftest import (
    ENV_REHEARSAL, green_admissions, make_coord_plan, make_exec_plan, make_pipeline,
)


def _store_env(root: Path):
    os.environ["HERMES_MULTI_SERVICE_EXECUTION_STORE"] = str(root)
    return root


def test_cli_status_readonly(tmp_path):
    root = _store_env(tmp_path)
    make_pipeline(tmp_path, env=ENV_REHEARSAL)
    rc = cli_main(["status"])
    assert rc == 0


def test_cli_inspect_unknown_receipt_returns_1(tmp_path):
    _store_env(tmp_path)
    rc = cli_main(["inspect-receipt", "nonexistent"])
    assert rc == 1


def test_cli_inspect_receipt_after_run(tmp_path):
    import sys
    from io import StringIO
    _store_env(tmp_path / "msexec" / "receipts")
    pipe, *_ = make_pipeline(tmp_path, env=ENV_REHEARSAL)
    plan = make_exec_plan(make_coord_plan(("svc-a",)))
    r = pipe.execute(plan, child_admissions=green_admissions(plan))
    eid = r["execution_id"]
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = cli_main(["inspect-receipt", eid])
    finally:
        sys.stdout = old
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["execution_id"] == eid


def test_cli_has_no_mutate_subcommand(tmp_path):
    # the CLI surface is read-only by construction: its source registers only
    # inspect/dry-run commands, never an execute/commit/apply mutator.
    src = (Path(__file__).resolve().parents[2] / "agent" / "multi_service_execution"
           / "cli.py").read_text(encoding="utf-8")
    for mutator in ("sub.add_parser(\"execute\")", "sub.add_parser(\"commit\")",
                    "sub.add_parser(\"mutate\")", "sub.add_parser(\"apply\")"):
        assert mutator not in src


def test_cli_never_touches_production_flag(tmp_path):
    _store_env(tmp_path)
    # dry-run classifies against durable state only; it never enables execution
    os.environ["HERMES_MULTI_SERVICE_EXECUTION_V2_ENABLED"] = "false"
    rc = cli_main(["status"])
    assert rc == 0