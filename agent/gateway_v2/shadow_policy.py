"""Shadow eligibility policy (Sprint 1.0.6.1) — DENY BY DEFAULT.

Shadow must NEVER run for ordinary traffic. ``V2ShadowPolicy.is_eligible``
returns True ONLY for requests that carry an explicit opt-in
(``metadata["runtime_v2_shadow"]`` parsed strictly as true/1/yes,
case-insensitive) AND satisfy every non-empty allowlist. No flag → not
eligible → LEGACY. No random rollout, no percentage, no hash sampling —
deterministic explicit eligibility only (§7-8).
"""

from typing import Any, Dict, List, Optional, Tuple

from .context_builder import GatewayRequest
from .flags import parse_flag

#: Metadata key a request must explicitly set to become shadow-eligible.
SHADOW_OPTIN_KEY = "runtime_v2_shadow"


class V2ShadowPolicy:
    """Deterministic, explicit-opt-in shadow eligibility (deny by default)."""

    def __init__(
        self,
        allowed_users: Optional[List[str]] = None,
        allowed_sessions: Optional[List[str]] = None,
    ) -> None:
        self._users = frozenset(allowed_users or [])
        self._sessions = frozenset(allowed_sessions or [])

    def is_eligible(self, request: GatewayRequest) -> Tuple[bool, str]:
        """(eligible, reason). Ordinary requests are never eligible."""
        opt_in = request.metadata.get(SHADOW_OPTIN_KEY)
        if not parse_flag(None if opt_in is None else str(opt_in)):
            return False, "no explicit runtime_v2_shadow opt-in"
        if self._users and request.user_id not in self._users:
            return False, "user not allowlisted"
        if self._sessions and request.session_id not in self._sessions:
            return False, "session not allowlisted"
        return True, "eligible"

    def summary(self) -> Dict[str, Any]:
        return {
            "allowed_users": sorted(self._users),
            "allowed_sessions": sorted(self._sessions),
            "deny_by_default": True,  # no flag → never eligible, always
        }


__all__ = ["V2ShadowPolicy", "SHADOW_OPTIN_KEY"]
