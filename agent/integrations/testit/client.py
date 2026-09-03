"""Read-only TestIT HTTP client foundation.

Phase 9.1.1 deliberately exposes only typed read methods.
No generic URL/method/header API is available to callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from agent.capability_broker.secrets import SecretValue

from .errors import (
    InvalidTestITConfiguration,
    InvalidTestITIdentifier,
    TestITAuthFailed,
    TestITNotFound,
    TestITRateLimited,
    TestITUnavailable,
    TestITUpstreamError,
)


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def validate_identifier(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidTestITIdentifier("identifier must be non-empty")

    forbidden = (
        "/",
        "\\",
        "..",
        "?",
        "#",
        "%",
        "\x00",
        "\r",
        "\n",
        "\t",
    )

    if any(item in value for item in forbidden):
        raise InvalidTestITIdentifier("identifier contains forbidden characters")

    if not _ID_RE.fullmatch(value):
        raise InvalidTestITIdentifier("identifier format is invalid")

    return value


def validate_base_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidTestITConfiguration("base URL is required")

    parsed = urlparse(value)

    if parsed.scheme != "https":
        raise InvalidTestITConfiguration("TestIT base URL must use https")

    if not parsed.hostname:
        raise InvalidTestITConfiguration("TestIT base URL must have a hostname")

    if parsed.username or parsed.password:
        raise InvalidTestITConfiguration("userinfo in TestIT URL is forbidden")

    if parsed.query or parsed.fragment:
        raise InvalidTestITConfiguration("query and fragment are forbidden")

    if parsed.port not in (None, 443):
        raise InvalidTestITConfiguration("non-standard TestIT port is forbidden")

    return value.rstrip("/")


class TestITTransport(Protocol):
    def get(self, path: str) -> Any:
        ...


@dataclass(slots=True)
class HttpxTestITTransport:
    base_url: str
    token: SecretValue
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        self.base_url = validate_base_url(self.base_url)

        if type(self.token) is not SecretValue:
            raise TypeError("token must be SecretValue")

        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise InvalidTestITConfiguration("timeout is out of bounds")

    def get(self, path: str) -> Any:
        if not isinstance(path, str) or not path.startswith("/"):
            raise InvalidTestITConfiguration("path must be absolute-relative")

        if "://" in path:
            raise InvalidTestITConfiguration("absolute URL is forbidden")

        headers = {
            "Authorization": f"PrivateToken {self.token._reveal_for_integration()}",
            "Accept": "application/json",
        }

        try:
            with httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = client.get(path)

        except httpx.RequestError as exc:
            raise TestITUnavailable("TestIT request unavailable") from exc

        if response.status_code in (401, 403):
            raise TestITAuthFailed("TestIT authentication failed")

        if response.status_code == 404:
            raise TestITNotFound("TestIT resource not found")

        if response.status_code == 429:
            raise TestITRateLimited("TestIT rate limited request")

        if response.status_code >= 400:
            raise TestITUpstreamError("TestIT upstream error")

        try:
            return response.json()
        except Exception as exc:
            raise TestITUpstreamError("TestIT returned invalid JSON") from exc


class TestITClient:
    """Typed read-only operations.

    Endpoint templates remain constructor-injected trusted configuration so
    Phase 9.1.1 does not invent production TestIT API paths.
    """

    def __init__(
        self,
        transport: TestITTransport,
        *,
        projects_path: str,
        testcases_path_template: str,
        testcase_path_template: str,
    ) -> None:
        self._transport = transport

        self._projects_path = self._validate_template(
            projects_path,
            placeholders=frozenset(),
        )
        self._testcases_path_template = self._validate_template(
            testcases_path_template,
            placeholders=frozenset({"project_id"}),
        )
        self._testcase_path_template = self._validate_template(
            testcase_path_template,
            placeholders=frozenset({"testcase_id"}),
        )

    @staticmethod
    def _validate_template(
        value: str,
        *,
        placeholders: frozenset[str],
    ) -> str:
        if not isinstance(value, str) or not value.startswith("/"):
            raise InvalidTestITConfiguration("invalid TestIT endpoint template")

        # Endpoint templates are trusted configuration, but still fail closed
        # against origin/path confusion. In particular, a scheme-relative
        # //host path must never be able to escape the configured TestIT
        # origin.
        if (
            value.startswith("//")
            or "\\" in value
            or ".." in value
            or "%" in value
            or "://" in value
            or "?" in value
            or "#" in value
            or "\x00" in value
            or "\r" in value
            or "\n" in value
            or "\t" in value
        ):
            raise InvalidTestITConfiguration("unsafe endpoint template")

        expected = {f"{{{name}}}" for name in placeholders}
        present = {
            part
            for part in re.findall(r"\{[^{}]+\}", value)
        }

        if present != expected:
            raise InvalidTestITConfiguration("unexpected endpoint placeholders")

        return value

    def list_projects(self) -> Any:
        return self._transport.get(self._projects_path)

    def list_testcases(self, project_id: str) -> Any:
        project_id = validate_identifier(project_id)
        return self._transport.get(
            self._testcases_path_template.format(project_id=project_id)
        )

    def get_testcase(self, testcase_id: str) -> Any:
        testcase_id = validate_identifier(testcase_id)
        return self._transport.get(
            self._testcase_path_template.format(testcase_id=testcase_id)
        )
