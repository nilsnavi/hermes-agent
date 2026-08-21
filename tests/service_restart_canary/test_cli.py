"""Test CLI: read-only commands; no execute command."""
import subprocess, sys
from agent.service_restart_canary import cli


def _run(*args):
    return cli.main(list(args))


def test_status():
    assert _run("status") == 0


def test_inspect():
    assert _run("inspect") == 0


def test_eligibility():
    assert _run("eligibility") == 0


def test_plan():
    assert _run("plan") == 0


def test_shadow_cmd():
    assert _run("shadow") == 0


def test_rehearsal_cmd():
    assert _run("rehearsal") == 0


def test_no_execute_command():
    rc = _run("execute", "hermes-aux-canary")
    assert rc == 1  # unknown command -> fail-closed
    assert "execute" not in cli._COMMANDS


def test_unknown_command():
    assert _run("garbage") == 1


def test_no_args():
    assert _run() == 0


def test_module_invocation():
    p = subprocess.run([sys.executable, "-m", "agent.service_restart_canary.cli", "status"],
                       capture_output=True, text=True, cwd=__file__.rsplit("/tests", 1)[0])
    assert p.returncode == 0
    assert "canary_enabled" in p.stdout