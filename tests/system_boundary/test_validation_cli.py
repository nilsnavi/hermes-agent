"""Sprint 1.3.3 §42/§43/§67/§68 — VALIDATION REGISTRY + CLI + LIVE.

Only a static verified registry may supply trusted validators; an LLM,
skill or plugin can never register one. CLI commands are read-only in
1.3.3. Live validation executes ZERO system mutations.
"""

import pytest

from agent.system_boundary import validation as val
from agent.system_boundary import models as m


# ── §42 static validator registry ───────────────────────────────────

def test_static_validator_registry_has_canonical_validators():
    reg = val.ValidatorRegistry()
    assert reg.validator_for("nginx config") == "nginx -t"
    assert reg.validator_for("systemd unit") == \
        "systemd-analyze verify"
    assert reg.validator_for("docker compose") == "docker compose config"
    assert reg.validator_for("ssh config") == "sshd -t"


def test_unknown_validator_unavailable():
    reg = val.ValidatorRegistry()
    assert reg.validator_for("mystery format") is None


def test_validation_unavailable_blocks():
    reg = val.ValidatorRegistry()
    decision = reg.decision_for("mystery format", required=True)
    assert decision == "VALIDATION_UNAVAILABLE"
    # BLOCK/REVALIDATE semantics
    assert decision != "SBL_OK"


def test_validator_registry_static_only():
    """No dynamic registration API — a plugin cannot add a validator."""
    reg = val.ValidatorRegistry()
    assert not hasattr(reg, "register")
    assert not hasattr(reg, "add_validator")


def test_validation_planner_known_validators():
    plan = val.plan_validation("nginx config")
    assert plan.validator == "nginx -t"
    assert plan.required is True


# ── §43 validator authority ─────────────────────────────────────────

def test_llm_cannot_create_trusted_validator():
    """validate_command with an unknown validator returns unavailable,
    regardless of the validator name supplied in the request."""
    reg = val.ValidatorRegistry()
    assert reg.decision_for("llm-invented-validator",
                            required=True) == "VALIDATION_UNAVAILABLE"


# ── §67 live validation ─────────────────────────────────────────────

def test_inspect_command_is_classification_only():
    """hermes sbl inspect-command returns classification, never
    executes the command."""
    from agent.system_boundary.cli import inspect_command

    out = inspect_command("systemctl --user restart hermes-gateway")
    assert out["verdict"] == "BLOCK"
    assert out["reason_code"] == "PROCESS_SELF_CONTROL_FORBIDDEN"
    assert out.get("executed") is False


def test_inspect_path_is_read_only(tmp_path):
    from agent.system_boundary.cli import inspect_path

    f = tmp_path / "x.txt"
    f.write_text("x")
    out = inspect_path(str(f))
    assert out["resource_class"] is not None
    assert out.get("wrote") is False
    # file unchanged
    assert f.read_text() == "x"


def test_sbl_status_reports_mode_and_version():
    from agent.system_boundary.cli import status

    out = status()
    assert "mode" in out
    assert "boundary_version" in out
    assert out["mode"] in ("off", "shadow", "enforce")


# ── §68 CLI forbidden commands in 1.3.3 ─────────────────────────────

def test_cli_has_no_mutation_commands():
    from agent.system_boundary import cli
    allowed = {c for c in dir(cli) if c.startswith("cmd_")}
    assert "cmd_execute" not in allowed
    assert "cmd_apply" not in allowed
    assert "cmd_restart" not in allowed
    assert "cmd_rollback" not in allowed
    assert "cmd_write" not in allowed
    assert "cmd_delete" not in allowed
