from agent.capability_broker.sanitization import sanitize


def test_recursive_sensitive_keys_are_redacted():
    source = {
        "name": "project",
        "nested": {
            "TOKEN": "abc123",
            "Authorization": "Bearer secret-value",
            "deep": [
                {
                    "client_secret": "hidden",
                    "safe": "visible",
                }
            ],
        },
    }

    result = sanitize(source)

    assert result["nested"]["TOKEN"] == "[REDACTED]"
    assert result["nested"]["Authorization"] == "[REDACTED]"
    assert result["nested"]["deep"][0]["client_secret"] == "[REDACTED]"
    assert result["nested"]["deep"][0]["safe"] == "visible"


def test_sensitive_key_matching_is_case_insensitive():
    result = sanitize(
        {
            "ApiKey": "a",
            "ACCESS-TOKEN": "b",
            "Refresh_Token": "c",
            "SET-COOKIE": "d",
        }
    )

    assert all(value == "[REDACTED]" for value in result.values())


def test_unknown_object_repr_is_not_executed_or_exposed():
    class Dangerous:
        def __repr__(self):
            return "password=secret-from-repr"

    result = sanitize({"value": Dangerous()})

    assert "secret-from-repr" not in result["value"]
    assert result["value"] == "[UNSUPPORTED:Dangerous]"


def test_nested_sequences_are_sanitized():
    result = sanitize(
        [
            {"password": "one"},
            {"safe": "two"},
        ]
    )

    assert result[0]["password"] == "[REDACTED]"
    assert result[1]["safe"] == "two"
