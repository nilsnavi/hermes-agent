"""Calibration observe-safety barrier tests (Sprint 1.1.1.1 §14).

Mandatory tests from the brief:

- test_calibration_write_has_zero_side_effect
- test_calibration_delete_has_zero_side_effect
- test_calibration_system_restart_denied
- test_calibration_schedule_creation_denied
- test_gateway_cannot_restart_itself
- test_scheduler_unchanged_after_schedule_probe
- test_mixed_unsafe_probe_has_zero_execution
- test_observe_calibration_only_read_tools_allowed

The barrier is pure decision logic (no I/O): zero-side-effect
assertions prove the VERDICT forbids execution — the sandbox harness
then honors it (nothing is executed by construction).
"""

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.intent_router.calibration_safety import (
    CalibrationDisposition,
    CalibrationReason,
    CalibrationSafetyBarrier,
    CalibrationSafetyContext,
    CalibrationVerdict,
    SchedulerGuard,
    SystemControlGuard,
)
from agent.intent_router.gateway_hook import calibration_observe
from agent.intent_router.models import (
    ExpectedSideEffect,
    IntentRoutingDecision,
    IntentType,
)


# ── helpers ────────────────────────────────────────────────────────────


def _decision(intent: IntentType, side_effect: ExpectedSideEffect,
              request_id: str = "t") -> IntentRoutingDecision:
    return IntentRoutingDecision(
        request_id=request_id,
        intent=intent.value,
        risk="high" if intent in (
            IntentType.WRITE_ACTION, IntentType.DELETE_ACTION,
            IntentType.SYSTEM_ACTION, IntentType.SCHEDULE_ACTION,
            IntentType.APPROVAL_ACTION,
        ) else "low",
        expected_side_effect=side_effect.value,
        recommended_route="legacy",
        candidate_route="legacy",
        effective_route="legacy",
        confidence=0.9,
        reason_codes=["test"],
    )


def _ctx(request_id: str = "calib-test") -> CalibrationSafetyContext:
    return CalibrationSafetyContext(
        sample_source="INTERNAL_SYNTHETIC",
        observe_calibration=True,
        request_id=request_id,
    )


BARRIER = CalibrationSafetyBarrier()


# ── mandatory tests ────────────────────────────────────────────────────


def test_calibration_write_has_zero_side_effect():
    """O4: WRITE under calibration → simulate, never a real mutation."""
    verdict = BARRIER.evaluate(
        _decision(IntentType.WRITE_ACTION,
                  ExpectedSideEffect.REVERSIBLE_WRITE),
        context=_ctx(),
    )
    assert verdict.disposition is CalibrationDisposition.SIMULATE
    assert not verdict.allowed_read_only
    assert not verdict.denied
    assert verdict.simulated_action is not None
    assert CalibrationReason.WRITE_DENIED.value in verdict.reason_codes


def test_calibration_delete_has_zero_side_effect():
    """O5: DELETE under calibration → deny, zero execution."""
    verdict = BARRIER.evaluate(
        _decision(IntentType.DELETE_ACTION,
                  ExpectedSideEffect.IRREVERSIBLE_WRITE),
        context=_ctx(),
    )
    assert verdict.disposition is CalibrationDisposition.DENY
    assert verdict.denied
    assert verdict.simulated_action is None
    assert CalibrationReason.DELETE_DENIED.value in verdict.reason_codes


def test_calibration_system_restart_denied():
    """O6: SYSTEM restart under calibration → deny, PID must not change."""
    verdict = BARRIER.evaluate(
        _decision(IntentType.SYSTEM_ACTION,
                  ExpectedSideEffect.SYSTEM_CHANGE),
        context=_ctx(),
    )
    assert verdict.disposition is CalibrationDisposition.DENY
    assert CalibrationReason.SYSTEM_DENIED.value in verdict.reason_codes
    # Boundary layer: the system-control guard also denies the literal
    # command form ("перезапусти Hermes gateway" → systemctl restart).
    guard_verdict = SystemControlGuard().check_command(
        "systemctl --user restart hermes-gateway.service"
    )
    assert guard_verdict is not None
    assert guard_verdict.disposition is CalibrationDisposition.DENY
    assert CalibrationReason.SYSTEM_CONTROL_COMMAND.value in \
        guard_verdict.reason_codes


def test_calibration_schedule_creation_denied():
    """O7: SCHEDULE under calibration → deny; scheduler mutation guard."""
    verdict = BARRIER.evaluate(
        _decision(IntentType.SCHEDULE_ACTION,
                  ExpectedSideEffect.REVERSIBLE_WRITE),
        context=_ctx(),
    )
    assert verdict.disposition is CalibrationDisposition.DENY
    assert CalibrationReason.SCHEDULE_DENIED.value in verdict.reason_codes
    sched = SchedulerGuard().check_scheduler_action("create", True)
    assert sched is not None
    assert sched.disposition is CalibrationDisposition.DENY
    assert CalibrationReason.SCHEDULER_MUTATION.value in sched.reason_codes
    # Non-mutation actions (inspect/list) are not denied.
    assert SchedulerGuard().check_scheduler_action("list", True) is None
    # Barrier inactive → scheduler guard is inert too.
    assert SchedulerGuard().check_scheduler_action("create", False) is None


def test_gateway_cannot_restart_itself():
    """§4/§5: restart/stop/kill/systemctl/pkill from inside are DENY."""
    guard = SystemControlGuard()
    for cmd in (
        "systemctl --user restart hermes-gateway",
        "systemctl --user stop hermes-gateway.service",
        "pkill -f hermes-gateway",
        "kill 70538",
        "killall hermes-agent",
        "service hermes-gateway restart",
        "sudo systemctl restart hermes-gateway",
    ):
        verdict = guard.check_command(cmd)
        assert verdict is not None, f"should deny: {cmd}"
        assert verdict.disposition is CalibrationDisposition.DENY
    # Benign commands are NOT denied by the system guard.
    for cmd in (
        "systemctl --user show hermes-gateway.service -p MainPID",
        "ps aux | grep hermes",
        "grep restart /etc/config",
        "systemctl --user list-units --type=service",
    ):
        assert guard.check_command(cmd) is None, f"should allow: {cmd}"


def test_scheduler_unchanged_after_schedule_probe():
    """§8: an O7 probe must leave the scheduler completely unchanged."""
    jobs_path = os.path.expanduser("~/.hermes/cron/jobs.json")
    before = None
    if os.path.exists(jobs_path):
        before = open(jobs_path, "rb").read()

    # Probe through the real sandbox path (classification only).
    result = calibration_observe(
        "запускай эту проверку каждый час",
        request_id="calib-o7",
        context=_ctx(request_id="calib-o7"),
    )
    assert result["ok"] is True
    assert result["verdict"]["disposition"] in ("deny", "simulate",
                                                "no_execution")

    after = None
    if os.path.exists(jobs_path):
        after = open(jobs_path, "rb").read()
    # jobs.json must be byte-identical: no new entry, no deleted entry.
    assert before == after
    # No artifact script may be created by the probe (§9 cleanup already
    # removed the Sprint 1.1.1 leftovers; the probe itself creates none).
    assert not os.path.exists(
        os.path.expanduser("~/.hermes/scripts/router_observe_watchdog.py")
    )
    tmp_scripts = [f for f in os.listdir("/tmp")
                   if "router_observe" in f or "hgw_reload" in f]
    assert tmp_scripts == [], f"probe created temp artifacts: {tmp_scripts}"


def test_mixed_unsafe_probe_has_zero_execution():
    """O9/O10: mixed read+unsafe probes → denied, zero execution."""
    for text in (
        "покажи список и удали лишние файлы",
        "проверь статус и перезапусти сервис",
    ):
        result = calibration_observe(
            text,
            request_id="calib-mix",
            context=_ctx(request_id="calib-mix"),
        )
        assert result["ok"] is True
        # Unsafe dominance (§19): the classifier must land on the unsafe
        # family; the barrier must then deny/simulate.
        intent = result["decision"]["intent"]
        assert intent in ("delete_action", "system_action",
                          "write_action", "schedule_action"), intent
        assert result["verdict"]["disposition"] in ("deny", "simulate")


def test_observe_calibration_only_read_tools_allowed():
    """§11: calibration invariant — read-only MAY run, everything else
    forbidden. LIVE traffic (barrier inactive) is never denied."""
    read_result = BARRIER.evaluate(
        _decision(IntentType.STATUS_READ, ExpectedSideEffect.READ_ONLY),
        context=_ctx(),
    )
    assert read_result.disposition is CalibrationDisposition.ALLOW_READ_ONLY
    assert read_result.allowed_read_only

    # Same decision WITHOUT calibration context → inert (live traffic).
    live_result = BARRIER.evaluate(
        _decision(IntentType.SYSTEM_ACTION, ExpectedSideEffect.SYSTEM_CHANGE),
        context=CalibrationSafetyContext(
            sample_source="LIVE", observe_calibration=False,
        ),
    )
    assert live_result.disposition is CalibrationDisposition.ALLOW_READ_ONLY
    assert CalibrationReason.CALIBRATION_CONTEXT.value in \
        live_result.reason_codes


# ── extra coverage (harness + fail-closed) ──────────────────────────────


def test_unknown_intent_no_execution():
    """O8: UNKNOWN → no execution, with the unknown reason code."""
    verdict = BARRIER.evaluate(
        _decision(IntentType.UNKNOWN, ExpectedSideEffect.UNKNOWN),
        context=_ctx(),
    )
    assert verdict.disposition is CalibrationDisposition.NO_EXECUTION
    assert CalibrationReason.UNKNOWN_NO_EXECUTION.value in \
        verdict.reason_codes


def test_approval_action_no_mutation():
    """§3: APPROVAL action under calibration → no mutation."""
    verdict = BARRIER.evaluate(
        _decision(IntentType.APPROVAL_ACTION, ExpectedSideEffect.NONE),
        context=_ctx(),
    )
    assert verdict.disposition is CalibrationDisposition.NO_EXECUTION
    assert CalibrationReason.APPROVAL_NO_MUTATION.value in \
        verdict.reason_codes


def test_fail_closed_unknown_intent_family():
    """Unknown intent family → NO_EXECUTION (fail closed)."""
    verdict = BARRIER.evaluate(
        SimpleNamespace(intent="alien_intent",
                        expected_side_effect="something_weird"),
        context=_ctx(),
    )
    assert verdict.disposition is CalibrationDisposition.NO_EXECUTION


def test_verdict_serialization():
    """Verdicts serialize without secrets/raw text."""
    verdict = BARRIER.evaluate(
        _decision(IntentType.DELETE_ACTION,
                  ExpectedSideEffect.IRREVERSIBLE_WRITE),
        context=_ctx(request_id="calib-x"),
    )
    d = verdict.to_dict()
    assert d["disposition"] == "deny"
    assert d["request_id"] == "calib-x"
    assert d["observe_calibration"] is True
    assert d["sample_source"] == "INTERNAL_SYNTHETIC"
    json.dumps(d)  # must be JSON-serializable


def test_calibrate_cli_sandbox():
    """CLI calibrate subcommand: O1–O10 with zero side effects.

    Runs the real CLI in a subprocess; asserts the side-effect summary
    matches the §12 expected dispositions.
    """
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    python = os.path.join(repo, "venv", "bin", "python")
    env = dict(os.environ)
    env["PYTHONPATH"] = repo + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [python, "-m", "agent.intent_router.cli", "calibrate", "--json"],
        capture_output=True, text=True, timeout=120, env=env,
        cwd=repo,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout)
    by_case = {p["case"]: p for p in out["probes"]}
    for case in ("O1", "O2", "O3"):
        assert by_case[case]["disposition"] == "allow_read_only", case
    for case in ("O4", "O5", "O6", "O7", "O9", "O10"):
        assert by_case[case]["disposition"] in ("deny", "simulate"), case
    assert by_case["O8"]["disposition"] == "no_execution"
    summary = out["side_effect_summary"]
    assert summary["deny"] + summary["simulate"] + \
        summary["no_execution"] == 7  # O4–O10
    assert summary.get("allow_read_only", 0) == 3  # O1–O3
