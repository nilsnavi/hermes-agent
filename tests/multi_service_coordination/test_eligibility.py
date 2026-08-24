from __future__ import annotations

from agent.multi_service_coordination.eligibility import (
    ChildVerdict,
    aggregate_eligibility,
    evaluate_child,
)


def test_evaluate_child_normalizes_common_shapes():
    assert evaluate_child(True) is ChildVerdict.ALLOW
    assert evaluate_child(False) is ChildVerdict.DENY
    assert evaluate_child(ChildVerdict.UNKNOWN) is ChildVerdict.UNKNOWN
    assert evaluate_child("ALLOW") is ChildVerdict.ALLOW
    assert evaluate_child("deny") is ChildVerdict.DENY
    assert evaluate_child(None) is ChildVerdict.UNKNOWN
    assert evaluate_child("whoknows") is ChildVerdict.DENY


def test_evaluate_child_uses_allowed_attribute_fail_closed():
    class _D:
        allowed = False

    class _A:
        allowed = True

    class _W:
        pass

    assert evaluate_child(_D()) is ChildVerdict.DENY
    assert evaluate_child(_A()) is ChildVerdict.ALLOW
    assert evaluate_child(_W()) is ChildVerdict.UNKNOWN


def test_all_allow_yields_allow():
    a = aggregate_eligibility({"a": True, "b": True, "c": True})
    assert a.allowed
    assert a.reason.value == "ALLOWED"
    assert not a.denied_children and not a.unknown_children


def test_any_deny_yields_parent_deny():
    a = aggregate_eligibility({"a": True, "b": False})
    assert not a.allowed
    assert a.reason.value == "CHILD_DENIED"
    assert a.denied_children == ("b",)


def test_unknown_never_allow():
    a = aggregate_eligibility({"a": True, "b": ChildVerdict.UNKNOWN})
    assert not a.allowed
    assert a.reason.value == "REVALIDATE_REQUIRED"
    assert a.unknown_children == ("b",)


def test_all_unknown_deny():
    a = aggregate_eligibility({"a": ChildVerdict.UNKNOWN, "b": ChildVerdict.UNKNOWN})
    assert not a.allowed


def test_deny_propagates_from_any_child_even_with_some_allowed():
    a = aggregate_eligibility({"a": True, "b": True, "c": False, "d": True})
    assert not a.allowed
    assert "c" in a.denied_children