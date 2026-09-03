"""Minimal read-only TestIT data contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class TestITProject:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class TestITTestCase:
    id: str
    name: str
    raw: Mapping[str, Any]
