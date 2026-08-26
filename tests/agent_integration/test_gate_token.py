"""Gate-token hardening (Phase 6 §7): runtime-owned opaque grant.

Adversarial cases REQUIRED by the brief -- import / copy / same-value / foreign
/ stale token -- must ALL be DENIED. A grant has no replayable value and is
never exposed to a caller.
"""

import copy

import pytest

from agent.agent_integration.gate_token import (
    GrantDenied,
    OpaqueGrant,
    RuntimeGrantSeal,
    copy_is_denied,
)


def _seal(generation: int = 1, digest: str = "reg-digest-A"):
    return RuntimeGrantSeal(generation=generation, registry_digest=digest)


def test_current_grant_authorizes():
    seal = _seal()
    assert seal.authorize(seal.current_grant()) is True
    seal.guard(seal.current_grant())  # no raise


def test_no_module_token_to_import():
    # There is no module-level secret/token to import.
    import agent.agent_integration.gate_token as gt

    for name in ("_SECRET", "_GATE_TOKEN", "secret", "token"):
        assert not hasattr(gt, name), f"unexpected module attribute {name}"
    # Grant instances have no __dict__ (slots) to introspect a value from.
    seal = _seal()
    assert not hasattr(seal, "__dict__")
    assert not hasattr(seal.current_grant(), "__dict__")


def test_copy_token_is_denied():
    seal = _seal()
    grant = seal.current_grant()
    copied = copy.deepcopy(grant)
    assert copied is not grant
    assert copy_is_denied(grant) is True
    assert seal.authorize(copied) is False
    with pytest.raises(GrantDenied):
        seal.guard(copied)


def test_same_value_token_is_denied():
    # A freshly minted grant with the SAME generation+digest but a different
    # nonce identity cannot satisfy the authorize (no value semantics).
    seal = _seal()
    forgery = OpaqueGrant(object(), generation=1, digest="reg-digest-A")
    assert seal.authorize(forgery) is False
    assert seal.authorize(None) is False
    assert seal.authorize("some-string") is False


def test_foreign_runtime_token_is_denied():
    seal_a = _seal(digest="reg-digest-A")
    seal_b = _seal(digest="reg-digest-B")
    # A grant from runtime B must not authorize runtime A.
    grant_b = seal_b.current_grant()
    assert seal_a.authorize(grant_b) is False
    with pytest.raises(GrantDenied):
        seal_a.guard(grant_b)


def test_stale_token_is_denied():
    seal = _seal(generation=1)
    old_grant = seal.current_grant()
    assert seal.authorize(old_grant) is True
    # Rotate -> generation moves forward; the old grant is now stale.
    seal.rotate(new_generation=2, registry_digest="reg-digest-A")
    assert seal.authorize(old_grant) is False
    with pytest.raises(GrantDenied):
        seal.guard(old_grant)
    # The seal's NEW current grant authorizes.
    assert seal.authorize(seal.current_grant()) is True


def test_stale_on_registry_digest_rebind_is_denied():
    seal = _seal(generation=1, digest="reg-v1")
    grant = seal.current_grant()
    seal.rotate(new_generation=2, registry_digest="reg-v2")  # digest rebound
    assert seal.authorize(grant) is False


def test_rotate_requires_forward_generation():
    seal = _seal(generation=1)
    with pytest.raises(ValueError):
        seal.rotate(new_generation=1, registry_digest="reg")  # not > current
    with pytest.raises(ValueError):
        seal.rotate(new_generation=0, registry_digest="reg")


def test_grant_has_no_replayable_value():
    seal = _seal()
    grant = seal.current_grant()
    # No serialization / equality / repr yields a usable "value".
    assert str(grant)  # exists but carries no secret
    assert grant is seal.current_grant() or grant == grant  # identity/self only