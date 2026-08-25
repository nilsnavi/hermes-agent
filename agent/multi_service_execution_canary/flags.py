"""Default-off fail-closed canary flags."""
from __future__ import annotations
import os
from collections.abc import Mapping
ENABLED = "HERMES_MULTI_SERVICE_CANARY_V2_ENABLED"
MODE = "HERMES_MULTI_SERVICE_CANARY_V2_MODE"
ALLOWED_MODES = ("off", "shadow", "canary")
REAL_CHILD_EXECUTION_ENABLED = False

def enabled(env: Mapping[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return str(e.get(ENABLED, "false")).strip().lower() in {"1", "true", "yes"}

def mode(env: Mapping[str, str] | None = None) -> str:
    e = os.environ if env is None else env
    value = str(e.get(MODE, "off")).strip().lower()
    return value if value in ALLOWED_MODES else "off"

def simulation_permitted(env: Mapping[str, str] | None = None) -> bool:
    return enabled(env) and mode(env) in {"shadow", "canary"} and not REAL_CHILD_EXECUTION_ENABLED

def real_execution_permitted(env: Mapping[str, str] | None = None) -> bool:
    return False
