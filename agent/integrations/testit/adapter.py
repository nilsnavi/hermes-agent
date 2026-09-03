"""Explicit TestIT operation adapter."""

from __future__ import annotations

from typing import Any, Mapping

from .client import TestITClient
from .errors import InvalidTestITIdentifier


class TestITAdapter:
    def __init__(self, client: TestITClient) -> None:
        self._client = client

    def list_projects(self, arguments: Mapping[str, Any]) -> Any:
        if arguments:
            raise InvalidTestITIdentifier(
                "list_projects does not accept arguments"
            )
        return self._client.list_projects()

    def list_testcases(self, arguments: Mapping[str, Any]) -> Any:
        if set(arguments) != {"project_id"}:
            raise InvalidTestITIdentifier(
                "list_testcases requires project_id"
            )

        return self._client.list_testcases(
            arguments["project_id"]
        )

    def get_testcase(self, arguments: Mapping[str, Any]) -> Any:
        if set(arguments) != {"testcase_id"}:
            raise InvalidTestITIdentifier(
                "get_testcase requires testcase_id"
            )

        return self._client.get_testcase(
            arguments["testcase_id"]
        )
