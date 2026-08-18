"""Capability Router feature flags (Sprint 1.3.0 §15, §28).

``HERMES_CAPABILITY_ROUTER_V2`` — strict 3-value parse:

    off       → capability router INERT (default; zero overhead)
    shadow    → compute capability decisions + compare vs legacy,
                never change routes
    enforce   → capability router decides for the EXACT 1.2.4 scope
                (STATUS_READ + SEARCH_READ limited production allowlist)

Default: ``off``. Unknown values fail closed to ``off`` (§15/§28).
"""

import os
from typing import Any, Dict, Optional

_CAPABILITY_ROUTER_ENV = "HERMES_CAPABILITY_ROUTER_V2"

#: Allowed modes (§15). Unknown → off (fail closed).
CAPABILITY_ROUTER_MODES = frozenset({"off", "shadow", "enforce"})

#: Sprint 1.3.1 §9 — normalized rollout policy modes. Unknown → off.
ROLLOUT_MODES = frozenset({
    "off", "shadow", "canary", "limited_enforce", "enforce",
})


def parse_capability_router_mode(value: Optional[str]) -> str:
    """Strict mode parse. None/garbage → off (fail closed)."""
    if value is None:
        return "off"
    mode = str(value).strip().lower()
    return mode if mode in CAPABILITY_ROUTER_MODES else "off"


def parse_rollout_mode(value: Optional[str]) -> str:
    """Sprint 1.3.1 §9 — normalize a rollout policy mode.

    off | shadow | canary | limited_enforce | enforce; None/garbage →
    off (fail closed). ``canary`` is accepted as a distinct normalized
    mode (the legacy canary surface), ``limited_enforce`` is the search
    production authority and ``enforce`` the capability-router mode.
    """
    if value is None:
        return "off"
    mode = str(value).strip().lower()
    return mode if mode in ROLLOUT_MODES else "off"


def read_capability_router_flags(
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Feature-flag read (§15). Default: off.

    The returned dict uses the ``capability_router_mode`` key so it can
    merge into the Intent Router flags dict (read_router_flags) without
    colliding with the search/canary keys.
    """
    env = environ if environ is not None else os.environ
    raw = env.get(_CAPABILITY_ROUTER_ENV)
    return {"capability_router_mode": parse_capability_router_mode(raw)}


__all__ = [
    "parse_capability_router_mode",
    "read_capability_router_flags",
    "CAPABILITY_ROUTER_MODES",
    "_CAPABILITY_ROUTER_ENV",
]
