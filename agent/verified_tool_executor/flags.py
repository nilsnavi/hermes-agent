"""Verified Tool Executor feature flag (Sprint 1.3.2 §61).

``HERMES_VERIFIED_TOOL_EXECUTOR_V2`` — strict boolean parse; the
default is FALSE (off). With the flag off, execution continues on the
Sprint 1.3.1 path (rollback ready). Unknown/garbage values fail closed
to False — "0" is never truthy.

Sprint 1.3.2 does NOT wire the executor into any production path: the
module is standalone and the flag exists so the activation sprint can
switch the migrated tools (STATUS_READ + operational_log_search) onto
the contract without code changes, and roll back by setting the flag
back to false.
"""

import os
from typing import Any, Dict, Optional

EXECUTOR_ENV = "HERMES_VERIFIED_TOOL_EXECUTOR_V2"

_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off", ""})


def parse_executor_flag(value: Optional[str]) -> bool:
    """Strict boolean parse. None/garbage → False (fail closed)."""
    if value is None:
        return False
    norm = str(value).strip().lower()
    if norm in _TRUE_VALUES:
        return True
    if norm in _FALSE_VALUES:
        return False
    return False  # unknown → off


def read_executor_flags(
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Read the executor flag from the environment (default off)."""
    env = environ if environ is not None else os.environ
    raw = env.get(EXECUTOR_ENV)
    return {"verified_tool_executor_v2": parse_executor_flag(raw)}


# ── Sprint 1.3.3 System Boundary Layer flags (§55) ──────────────────

SBL_ENABLED_ENV = "HERMES_SBL_V2_ENABLED"
SBL_MODE_ENV = "HERMES_SBL_V2_MODE"
SBL_GRAPH_ENV = "HERMES_SBL_GRAPH_ENABLED"
SBL_DEEP_AUDIT_ENV = "HERMES_SBL_DEEP_AUDIT"

#: canonical modes (§55): off / shadow / enforce
SBL_MODES = ("off", "shadow", "enforce")


def parse_sbl_mode(value: Optional[str]) -> str:
    """Strict mode parse — unknown/garbage → 'shadow' (safe default:
    analytics without affecting the read path, critical mutations
    still fail closed)."""
    if value is None:
        return "shadow"
    norm = str(value).strip().lower()
    if norm in SBL_MODES:
        return norm
    return "shadow"


def read_sbl_flags(
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Read the SBL flags (§55).

    Initial production state:
        ENABLED=true, MODE=shadow, GRAPH_ENABLED=true, DEEP_AUDIT=false
    """
    env = environ if environ is not None else os.environ
    return {
        "sbl_v2_enabled": parse_executor_flag(
            env.get(SBL_ENABLED_ENV, "true")),
        "sbl_v2_mode": parse_sbl_mode(env.get(SBL_MODE_ENV)),
        "sbl_graph_enabled": parse_executor_flag(
            env.get(SBL_GRAPH_ENV, "true")),
        "sbl_deep_audit": parse_executor_flag(
            env.get(SBL_DEEP_AUDIT_ENV, "false")),
    }


__all__ = [
    "parse_executor_flag",
    "read_executor_flags",
    "EXECUTOR_ENV",
    "SBL_ENABLED_ENV",
    "SBL_MODE_ENV",
    "SBL_GRAPH_ENV",
    "SBL_DEEP_AUDIT_ENV",
    "SBL_MODES",
    "parse_sbl_mode",
    "read_sbl_flags",
]
