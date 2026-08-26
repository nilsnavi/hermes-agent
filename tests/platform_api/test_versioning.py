"""API versioning contract tests."""

import pytest

from agent.platform_api.versioning import ApiVersion, InvalidApiVersion, parse_request_version


def test_parse_v1():
    assert ApiVersion.parse("v1") == ApiVersion(1, 0)
    assert ApiVersion.parse("1") == ApiVersion(1, 0)


def test_parse_minor():
    assert ApiVersion.parse("v1.2") == ApiVersion(1, 2)


def test_parse_rejects_malformed():
    for raw in ("", "v", "0", "v0.1", "abc", "1.2.3", "v1.0"):
        with pytest.raises(InvalidApiVersion):
            ApiVersion.parse(raw)


def test_parse_rejects_non_string():
    with pytest.raises(InvalidApiVersion):
        ApiVersion.parse(1)  # type: ignore[arg-type]


def test_request_version_must_be_supported():
    supported = frozenset({ApiVersion(1, 0)})
    assert parse_request_version("v1", supported=supported) == ApiVersion(1, 0)
    with pytest.raises(InvalidApiVersion):
        parse_request_version("v2", supported=supported)


def test_prefix():
    assert ApiVersion(3, 1).prefix == "v3"


def test_request_version_requires_nonempty_supported():
    with pytest.raises(InvalidApiVersion):
        parse_request_version("v1", supported=frozenset())