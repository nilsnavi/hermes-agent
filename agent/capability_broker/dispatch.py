"""Trusted integration dispatch.

Concrete action names are resolved by explicit code paths. No getattr(),
dynamic imports, arbitrary method names, or caller-supplied transport data.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from agent.integrations.testit.adapter import TestITAdapter
from agent.integrations.testit.errors import (
    InvalidTestITConfiguration,
    InvalidTestITIdentifier,
    TestITAuthFailed,
    TestITNotFound,
    TestITRateLimited,
    TestITUnavailable,
    TestITUpstreamError,
)

from .errors import (
    InvalidCapabilityRequest,
    IntegrationUnavailable,
    UnknownCapability,
    UpstreamAuthFailed,
    UpstreamError,
    UpstreamNotFound,
    UpstreamRateLimited,
)
from .secrets import SecretValue


class IntegrationDispatcher(Protocol):
    def execute(
        self,
        action: str,
        arguments: Mapping[str, Any],
        secrets: Mapping[str, SecretValue],
    ) -> Any:
        ...


TestITAdapterFactory = Callable[
    [Mapping[str, SecretValue]],
    TestITAdapter,
]


class TestITDispatcher:
    """Closed dispatch table for the Phase 9.1.1 TestIT read surface."""

    def __init__(self, adapter_factory: TestITAdapterFactory) -> None:
        if not callable(adapter_factory):
            raise TypeError("adapter_factory must be callable")
        self._adapter_factory = adapter_factory

    def execute(
        self,
        action: str,
        arguments: Mapping[str, Any],
        secrets: Mapping[str, SecretValue],
    ) -> Any:
        adapter = self._adapter_factory(secrets)

        if type(adapter) is not TestITAdapter:
            raise TypeError("adapter_factory must return TestITAdapter")

        try:
            if action == "list_projects":
                return adapter.list_projects(arguments)

            if action == "list_testcases":
                return adapter.list_testcases(arguments)

            if action == "get_testcase":
                return adapter.get_testcase(arguments)

            raise UnknownCapability("integration action is not registered")

        except InvalidTestITIdentifier as exc:
            raise InvalidCapabilityRequest(
                "invalid TestIT operation argument"
            ) from exc

        except InvalidTestITConfiguration as exc:
            raise IntegrationUnavailable(
                "TestIT trusted configuration is invalid"
            ) from exc

        except TestITAuthFailed as exc:
            raise UpstreamAuthFailed(
                "TestIT authentication failed"
            ) from exc

        except TestITNotFound as exc:
            raise UpstreamNotFound(
                "TestIT resource not found"
            ) from exc

        except TestITRateLimited as exc:
            raise UpstreamRateLimited(
                "TestIT rate limited request"
            ) from exc

        except TestITUnavailable as exc:
            raise IntegrationUnavailable(
                "TestIT integration unavailable"
            ) from exc

        except TestITUpstreamError as exc:
            raise UpstreamError(
                "TestIT upstream error"
            ) from exc
