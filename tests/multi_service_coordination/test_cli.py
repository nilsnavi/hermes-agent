from __future__ import annotations

import json
import subprocess
import sys

from agent.multi_service_coordination.cli import build_parser


def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "agent.multi_service_coordination.cli", *args],
        capture_output=True, text=True,
    )


def test_inspect_graph_is_read_only_and_reports_flags():
    r = _cli("inspect-graph")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert "registry_digest" in data
    assert data["max_services"] == 3
    assert data["flags"]["mode"] in ("off", "shadow", "rehearsal")


def test_inspect_plan_unknown_is_fail_closed():
    r = _cli("inspect-plan", "does-not-exist")
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_inspect_transaction_unknown_is_fail_closed():
    r = _cli("inspect-transaction", "nope")
    assert r.returncode == 1


def test_shadow_evaluate_is_read_only():
    r = _cli("shadow-evaluate", "--n", "50")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["correctness"] == 100.0
    assert data["real_multi_service_adapter_calls"] == 0


def test_parser_has_no_execute_command():
    parser = build_parser()
    sub = parser._subparsers
    names = set()
    for action in getattr(sub, "_group_actions", []) or []:
        for name, subparser in getattr(action, "choices", {}).items():
            names.add(name)
    assert names == {"inspect-plan", "inspect-transaction", "inspect-graph", "shadow-evaluate"}
    assert "execute" not in names


def test_parser_requires_subcommand():
    r = _cli()
    assert r.returncode != 0