"""ShadowComparison + mismatch taxonomy tests (Sprint 1.0.6.1 §16-17)."""

from agent.gateway_v2.comparison import (
    INVALID_PLAN,
    MISMATCH_CODES,
    NO_MISMATCH,
    NO_PLAN,
    SHADOW_EXCEPTION,
    TOOL_NOT_ALLOWED,
    WOULD_REQUIRE_APPROVAL,
    WOULD_REQUIRE_WRITE,
    ShadowComparison,
    build_comparison,
)


def _report(**kw):
    base = {
        "request_id": "r1", "ok": True, "eligible": True, "reason": None,
        "plan_valid": True, "stop_reason": "completed", "timed_out": False,
        "predicted_steps": 1, "predicted_tool_calls": 1,
        "would_require_write": False, "would_require_approval": False,
        "denied_steps": 0, "issues": [],
    }
    base.update(kw)
    return base


def test_taxonomy_complete():
    expected = {
        "NO_PLAN", "INVALID_PLAN", "TOOL_NOT_ALLOWED", "WOULD_REQUIRE_WRITE",
        "WOULD_REQUIRE_APPROVAL", "BUDGET_EXCEEDED", "SHADOW_EXCEPTION",
        "NO_MISMATCH",
    }
    assert MISMATCH_CODES == expected


def test_no_mismatch():
    c = build_comparison("r1", _report())
    assert c.mismatch_flags == [NO_MISMATCH]
    assert c.legacy_success is True and c.shadow_success is True


def test_write_flag():
    c = build_comparison("r1", _report(would_require_write=True))
    assert c.mismatch_flags == [WOULD_REQUIRE_WRITE]


def test_approval_flag():
    c = build_comparison("r1", _report(would_require_approval=True))
    assert c.mismatch_flags == [WOULD_REQUIRE_APPROVAL]


def test_denied_flag():
    c = build_comparison("r1", _report(denied_steps=1, predicted_tool_calls=0))
    assert c.mismatch_flags == [TOOL_NOT_ALLOWED]


def test_invalid_plan_flag():
    c = build_comparison("r1", _report(plan_valid=False, issues=["unknown tool x"]))
    assert c.mismatch_flags == [INVALID_PLAN]


def test_no_plan_flag():
    c = build_comparison("r1", _report(plan_valid=False, predicted_steps=0,
                                       issues=[]))
    assert c.mismatch_flags == [NO_PLAN]


def test_exception_flag():
    c = build_comparison("r1", _report(ok=False, reason="shadow error: boom"))
    assert c.mismatch_flags == [SHADOW_EXCEPTION]


def test_timeout_flag():
    c = build_comparison("r1", _report(timed_out=True, ok=False))
    assert c.mismatch_flags == [SHADOW_EXCEPTION]


def test_legacy_failure_flagged_as_exception_not_mismatch():
    c = build_comparison("r1", _report(), legacy_success=False)
    assert c.mismatch_flags == [SHADOW_EXCEPTION]


def test_comparison_has_no_raw_content():
    c = ShadowComparison("r1", legacy_success=True, shadow_success=True,
                         mismatch_flags=[NO_MISMATCH])
    d = c.to_dict()
    assert d["request_id"] == "r1"
    assert "goal" not in d and "prompt" not in str(d)
    assert "secret" not in str(d)


def test_budget_exceeded_constant_usable():
    """BUDGET_EXCEEDED is part of the taxonomy (reserved for future
    budget-prediction mismatches)."""
    from agent.gateway_v2.comparison import BUDGET_EXCEEDED

    assert BUDGET_EXCEEDED in MISMATCH_CODES
