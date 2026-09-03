import pytest

from agent.capability_broker.secrets import (
    ScopedSecretResolver,
    SecretAccessDenied,
    SecretUnavailable,
    SecretValue,
)


def backend(values):
    return lambda name: values.get(name)


def test_secret_value_never_reveals_via_str_or_repr():
    secret = SecretValue("super-secret-token")
    assert "super-secret-token" not in str(secret)
    assert "super-secret-token" not in repr(secret)
    assert str(secret) == "[REDACTED]"


def test_internal_reveal_returns_actual_value():
    secret = SecretValue("real-token")
    assert secret._reveal_for_integration() == "real-token"


def test_resolver_allows_only_trusted_names():
    resolver = ScopedSecretResolver(
        frozenset({"TESTIT_TOKEN"}),
        backend=backend({"TESTIT_TOKEN": "token-value"}),
    )

    value = resolver.resolve("TESTIT_TOKEN")
    assert value._reveal_for_integration() == "token-value"


def test_request_cannot_choose_unscoped_secret():
    resolver = ScopedSecretResolver(
        frozenset({"TESTIT_TOKEN"}),
        backend=backend(
            {
                "TESTIT_TOKEN": "token-value",
                "OPENAI_API_KEY": "must-not-leak",
            }
        ),
    )

    with pytest.raises(SecretAccessDenied):
        resolver.resolve("OPENAI_API_KEY")


def test_missing_secret_fails_closed():
    resolver = ScopedSecretResolver(
        frozenset({"TESTIT_TOKEN"}),
        backend=backend({}),
    )

    with pytest.raises(SecretUnavailable):
        resolver.resolve("TESTIT_TOKEN")


def test_backend_exception_is_sanitized():
    def broken(_name):
        raise RuntimeError("secret backend exploded TOKEN=plaintext")

    resolver = ScopedSecretResolver(
        frozenset({"TESTIT_TOKEN"}),
        backend=broken,
    )

    with pytest.raises(SecretUnavailable) as exc:
        resolver.resolve("TESTIT_TOKEN")

    assert "plaintext" not in str(exc.value)


def test_resolve_required_returns_only_allowlisted_names():
    resolver = ScopedSecretResolver(
        frozenset({"TESTIT_URL", "TESTIT_TOKEN"}),
        backend=backend(
            {
                "TESTIT_URL": "https://testit.invalid",
                "TESTIT_TOKEN": "token",
                "UNRELATED_SECRET": "never",
            }
        ),
    )

    resolved = resolver.resolve_required()

    assert set(resolved) == {"TESTIT_URL", "TESTIT_TOKEN"}
    assert "UNRELATED_SECRET" not in resolved
