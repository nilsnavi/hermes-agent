import json
import os
import subprocess
import sys


def run_cli(tmp_path, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    return subprocess.run(
        [sys.executable, "-m", "agent.multi_service_execution_canary.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def test_status_is_read_only_and_reports_permanent_safety_boundaries(tmp_path):
    before = set(tmp_path.iterdir())
    completed = run_cli(tmp_path, "status")
    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload["service_ids"] == ["canary-service-a", "canary-service-b"]
    assert payload["registry_size"] == 2
    assert payload["real_child_execution_enabled"] is False
    assert payload["system_control"] == "OFF"
    assert payload["generic_service_control"] == "DENIED"
    assert set(tmp_path.iterdir()) == before


def test_inspect_receipt_round_trips_json_without_mutating_input(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"decision":"UNKNOWN_OUTCOME","real_effect_count":0}')
    before = receipt.read_bytes()
    completed = run_cli(tmp_path, "inspect-receipt", str(receipt))
    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "decision": "UNKNOWN_OUTCOME",
        "real_effect_count": 0,
    }
    assert receipt.read_bytes() == before


def test_dry_run_is_inspect_only_with_zero_real_adapter_calls(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text('{"service_ids":["canary-service-a","canary-service-b"]}')
    completed = run_cli(tmp_path, "dry-run", str(plan))
    payload = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert payload == {
        "decision": "INSPECT_ONLY",
        "input_keys": ["service_ids"],
        "real_adapter_calls": 0,
    }


def test_cli_rejects_mutator_verbs(tmp_path):
    for verb in ("execute", "commit", "restart", "compensate", "kill-switch-reset"):
        completed = run_cli(tmp_path, verb)
        assert completed.returncode != 0
        assert "invalid choice" in completed.stderr
