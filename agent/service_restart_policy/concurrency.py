"""Restart concurrency policy; live multi-service concurrency stays disabled."""
from __future__ import annotations


class RestartConcurrencyPolicy:
    def __init__(self, live_concurrency_enabled: bool = False) -> None:
        self.live_concurrency_enabled = bool(live_concurrency_enabled)

    def allowed(
        self,
        service_id: str,
        *,
        active_services: tuple[str, ...] = (),
        intersecting_graph: bool = False,
    ) -> bool:
        if not service_id or service_id in active_services:
            return False
        if not active_services:
            return True
        if not self.live_concurrency_enabled or intersecting_graph:
            return False
        return True


__all__ = ["RestartConcurrencyPolicy"]
