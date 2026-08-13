"""Integration registry (Sprint 0.7 §6/§13) — thread-safe lifecycle state.

Home Assistant is handled as the canonical decision case: *unused* (no
skill/job/tool in use, cron toolsets off) and endpoint ``homeassistant.local``
unresolvable → registered as enabled=false / DISABLED with an explicit
reason.  Nothing is deleted from config; network/DNS untouched.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

from .domain import IntegrationStatus
from .domain import IntegrationState as St

# Canonical decision: HA is unused + endpoint unavailable → DISABLED.
DEFAULT_MANAGED: Dict[str, IntegrationStatus] = {
    "homeassistant": IntegrationStatus(
        integration="homeassistant",
        enabled=False,
        health=St.DISABLED.value,
        required=False,
        config_source="~/.hermes/.env (HASS_URL/HASS_TOKEN)",
        endpoint="homeassistant.local:8123",
        auth_type="HASS_TOKEN",
        used_by=["none (cron toolset off, no skill/job usage)"],
        retry_policy="none",
        reason="unused / endpoint homeassistant.local unresolvable",
    ),
    "atlassian_mcp": IntegrationStatus(
        integration="atlassian_mcp",
        enabled=True,
        health=St.HEALTHY.value,
        required=False,
        config_source="config.yaml mcp_servers",
        endpoint="(MCP, local)",
        auth_type="mcp",
        used_by=["agent MCP tools"],
        retry_policy="none",
    ),
    "chrome_devtools_mcp": IntegrationStatus(
        integration="chrome_devtools_mcp",
        enabled=True,
        health=St.HEALTHY.value,
        required=False,
        config_source="config.yaml mcp_servers",
        endpoint="(MCP, local)",
        auth_type="mcp",
        used_by=["agent MCP tools"],
        retry_policy="none",
    ),
    "telegram": IntegrationStatus(
        integration="telegram",
        enabled=True,
        health=St.HEALTHY.value,
        required=True,
        config_source="~/.hermes/.env (TELEGRAM_BOT_TOKEN)",
        endpoint="api.telegram.org (via SOCKS5)",
        auth_type="bot_token",
        used_by=["gateway messaging", "cron delivery"],
        retry_policy="exponential+jitter",
    ),
    "github": IntegrationStatus(
        integration="github",
        enabled=True,
        health=St.HEALTHY.value,
        required=False,
        config_source="~/.hermes/.env (GH_*)",
        endpoint="api.github.com",
        auth_type="gh token",
        used_by=["github-report cron", "watchdog"],
        retry_policy="exponential+jitter",
    ),
}


class IntegrationRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[str, IntegrationStatus] = {
            k: IntegrationStatus(**v.__dict__) for k, v in DEFAULT_MANAGED.items()
        }

    def get(self, integration: str) -> Optional[IntegrationStatus]:
        with self._lock:
            st = self._state.get(integration)
            return IntegrationStatus(**st.__dict__) if st else None

    def list(self) -> List[IntegrationStatus]:
        with self._lock:
            return [IntegrationStatus(**st.__dict__) for st in self._state.values()]

    def register(self, status: IntegrationStatus) -> None:
        with self._lock:
            self._state[status.integration] = IntegrationStatus(**status.__dict__)

    def set_disabled(self, integration: str, reason: str) -> bool:
        with self._lock:
            st = self._state.get(integration)
            if st is None:
                return False
            st.enabled = False
            st.health = St.DISABLED.value
            st.reason = reason
            st.retry_policy = "none"
            return True

    def mark_success(self, integration: str) -> None:
        with self._lock:
            st = self._state.get(integration)
            if st is None:
                return
            st.health = St.HEALTHY.value
            st.last_success = time.strftime("%Y-%m-%d %H:%M:%S")
            st.failure_count = 0
            st.attempt = 0
            st.error_class = None
            st.next_retry_at = None

    def mark_failure(self, integration: str, error_class: str,
                     attempt: int, next_retry_at: Optional[float] = None) -> None:
        with self._lock:
            st = self._state.get(integration)
            if st is None:
                return
            st.health = St.UNAVAILABLE.value
            st.last_failure = time.strftime("%Y-%m-%d %H:%M:%S")
            st.failure_count += 1
            st.error_class = error_class
            st.attempt = attempt
            st.next_retry_at = next_retry_at

    def is_disabled(self, integration: str) -> bool:
        with self._lock:
            st = self._state.get(integration)
            return bool(st and not st.enabled)


HA_MANAGED = DEFAULT_MANAGED  # alias kept for __init__ imports


# module-level default instance (lazy)
_DEFAULT: Optional[IntegrationRegistry] = None


def get_registry() -> IntegrationRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        reg = IntegrationRegistry()
        for _name, _st in DEFAULT_MANAGED.items():
            reg.register(_st)
        _DEFAULT = reg
    return _DEFAULT


def integration_disabled(platform_name: str) -> bool:
    """Gateway hook: is this platform integration administratively disabled?"""
    return get_registry().is_disabled(platform_name)