"""Sprint 1.3.10 flags (off/shadow/canary; unknown -> off)."""
import os
from collections.abc import Mapping

ENABLED = "HERMES_SERVICE_RELOAD_CANARY_V2_ENABLED"
MODE = "HERMES_SERVICE_RELOAD_CANARY_V2_MODE"


def mode(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    m = env.get(MODE, "off").strip().lower()
    return m if m in ("off", "shadow", "canary") else "off"


def enabled(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get(ENABLED, "false").strip().lower() == "true"
