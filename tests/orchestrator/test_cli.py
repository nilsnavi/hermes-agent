"""CLI tests (Sprint 1.0.5 §61) — fake tools only."""

import os

from agent.orchestrator.cli import main


def test_run_demo(tmp_path, capsys):
    code = main(["run-demo", "--steps", "3"])
    out = capsys.readouterr().out
    assert code == 0
    assert "run_id" in out
    assert "completed" in out
    assert "tool_calls" in out
    assert "db" in out  # demo db path printed


def test_run_demo_zero_steps_is_no_plan(tmp_path, capsys):
    code = main(["run-demo", "--steps", "0"])
    out = capsys.readouterr().out
    assert code == 0
    assert "no_plan" in out


def test_inspect_requires_db(capsys):
    """--db is required for inspect — argparse refuses with exit code 2."""
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["inspect", "run-1"])
    assert exc.value.code == 2
