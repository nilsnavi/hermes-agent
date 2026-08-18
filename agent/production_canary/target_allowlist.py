"""Sprint 1.3.7 §4/§6 — the ONE exact production canary target allowlist.

Rules (fail-closed, no glob/prefix-only):
- Only the exact canonical path is allowed.
- Symlink to/from target or symlink parent -> deny (resolve must not change).
- Target must not be config.yaml / state.db / .env / ssh / etc / run / cron.
- Target parent directory must be owned by the invoking user, mode 700.
- Env-supplied target hint must equal the compiled canonical path.
"""
from __future__ import annotations

import getpass
import os
from dataclasses import dataclass

from .core import CANARY_DENY_FINGERPRINTS, CANARY_TARGET


@dataclass(frozen=True)
class TargetResolution:
    allowed: bool
    realpath: str | None = None
    reason: str = ""


class TargetDenied(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TargetAllowlist:
    """Exact single-target allowlist (canonical path injected for tests)."""

    def __init__(self, canonical: str | None = None, expected_owner: str | None = None) -> None:
        self.canonical = os.path.abspath(canonical or CANARY_TARGET)
        self.expected_owner = expected_owner or getpass.getuser()

    def resolve(self, target: str, *, env_hint: str | None = None) -> TargetResolution:
        """Resolve and authorize an EXACT target identity."""
        # 1) exact string equality with the compiled canonical path
        if target != self.canonical:
            return TargetResolution(False, reason="not exact canonical target")
        # 2) env hint, if present, must equal canonical too (never widens trust)
        if env_hint and os.path.abspath(env_hint) != self.canonical:
            return TargetResolution(False, reason="env target hint mismatch")

        real = os.path.realpath(target)
        # 3) realpath must not differ (no symlink to/from target)
        if real != target:
            return TargetResolution(False, realpath=real, reason="symlink resolution changed target")

        # 4) no symlink parent
        parent = os.path.dirname(target)
        if os.path.realpath(parent) != parent:
            return TargetResolution(False, realpath=os.path.realpath(parent),
                                    reason="symlink parent")

        # 5) hard-deny by fingerprint classes
        lower = target.lower()
        for deny in CANARY_DENY_FINGERPRINTS:
            if deny in lower:
                return TargetResolution(False, reason=f"deny class: {deny}")

        # 6) existing parent must be a real dir owned by expected owner, mode 700
        if os.path.isdir(parent):
            st = os.stat(parent)
            # owner check needs uid->name; require owner match via uid comparison
            try:
                import pwd
                owner = pwd.getpwuid(st.st_uid).pw_name
            except Exception:
                owner = str(st.st_uid)
            if owner != self.expected_owner:
                return TargetResolution(False, reason=f"parent owner mismatch: {owner}")
            if (st.st_mode & 0o777) != 0o700:
                return TargetResolution(False, reason="parent mode != 700")

        return TargetResolution(True, realpath=target, reason="ok")

    def is_allowed(self, target: str, **kw) -> bool:
        try:
            return self.resolve(target, **kw).allowed
        except TargetDenied:
            return False
