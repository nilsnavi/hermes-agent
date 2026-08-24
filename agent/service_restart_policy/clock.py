"""Internal trusted clocks for restart authority decisions."""
from __future__ import annotations

import time
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class Clock(Protocol):
    @property
    def provenance(self) -> str: ...

    def monotonic(self) -> float: ...

    def wall_time(self) -> float: ...


class SystemClock:
    """Production clock: monotonic authority time, wall audit time only."""

    def __init__(self) -> None:
        try:
            boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        except OSError:
            # No stable boot identity: cross-process persisted monotonic reuse is unsafe.
            boot = f"boot-unknown:{os.getpid()}:{secrets.token_urlsafe(16)}"
        self._provenance = f"{boot}:{time.get_clock_info('monotonic').implementation}"

    @property
    def provenance(self) -> str:
        return self._provenance

    def monotonic(self) -> float:
        return time.monotonic()

    def wall_time(self) -> float:
        return time.time()


@dataclass
class ControlledClock:
    """Deterministic construction-time test clock."""

    value: float = 0.0
    wall_value: float = 0.0
    provenance_value: str = "controlled-clock"

    @property
    def provenance(self) -> str:
        return self.provenance_value

    def monotonic(self) -> float:
        return self.value

    def wall_time(self) -> float:
        return self.wall_value

    def advance(self, seconds: float) -> None:
        self.value += seconds
        self.wall_value += seconds


__all__ = ["Clock", "ControlledClock", "SystemClock"]
