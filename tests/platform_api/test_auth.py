"""Auth boundary contract tests."""

import pytest

from agent.platform_api.auth import (
    AuthenticationError,
    Principal,
    authenticate_bearer,
    enforce_tenant_boundary,
)


def _principal(tenant="t1", user="u1", scopes=("tasks.submit", "memory.read")) -> Principal:
    return Principal(
        tenant_id=tenant, principal_id="p1", user_id=user, scopes=set(scopes),
    )


def test_principal_requires_tenant():
    with pytest.raises(AuthenticationError):
        Principal(tenant_id="", principal_id="p")


def test_principal_require_scope():
    principal = _principal(scopes=("memory.read",))
    principal.require_scope("memory.read")
    with pytest.raises(AuthenticationError):
        principal.require_scope("tasks.submit")


def test_authenticate_bearer_valid_token():
    principal = authenticate_bearer(
        "tok-123",
        expected_token="tok-123",
        tenant_id="t1",
        principal_id="p1",
        supported_scopes={"tasks.submit"},
    )
    assert principal.principal_id == "p1"
    assert principal.tenant_id == "t1"


def test_authenticate_bearer_missing_or_invalid_token():
    with pytest.raises(AuthenticationError):
        authenticate_bearer(
            "",
            expected_token="tok",
            tenant_id="t1",
            principal_id="p1",
            supported_scopes={"a"},
        )
    with pytest.raises(AuthenticationError):
        authenticate_bearer(
            "wrong",
            expected_token="tok",
            tenant_id="t1",
            principal_id="p1",
            supported_scopes={"a"},
        )


def test_tenant_boundary_accepts_matching():
    principal = _principal(tenant="t1")
    assert enforce_tenant_boundary(principal, "t1") == "t1"


def test_tenant_boundary_rejects_body_tenant_mismatch():
    principal = _principal(tenant="t1")
    # A request body claiming another tenant is denied.
    with pytest.raises(AuthenticationError):
        enforce_tenant_boundary(principal, "t2")


def test_tenant_boundary_principal_is_authority_when_body_empty():
    principal = _principal(tenant="t1")
    assert enforce_tenant_boundary(principal, "") == "t1"
    assert enforce_tenant_boundary(principal, None) == "t1"


def test_tenant_boundary_rejects_non_principal():
    with pytest.raises(AuthenticationError):
        enforce_tenant_boundary(object(), "t1")  # type: ignore[arg-type]


def test_auth_models_carry_no_execution_authority():
    principal = _principal()
    assert not hasattr(principal, "execute")
    assert not hasattr(principal, "run")
    assert not hasattr(principal, "authorize")