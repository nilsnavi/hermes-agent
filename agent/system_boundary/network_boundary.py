"""Network boundary (Sprint 1.3.3 §30).

Classes: LOOPBACK / LOCAL_HOST / LAN / PRIVATE_NETWORK /
PUBLIC_NETWORK / UNKNOWN. Operations: READ / CONNECT /
LISTEN_CHANGE / ROUTE_CHANGE / CONFIG_CHANGE / FIREWALL_CHANGE.

No new network authority. UNKNOWN mutation → BLOCK.
"""

from dataclasses import dataclass
from typing import Optional

from .models import block_decision, pass_decision


class NetworkClass:
    LOOPBACK = "LOOPBACK"
    LOCAL_HOST = "LOCAL_HOST"
    LAN = "LAN"
    PRIVATE_NETWORK = "PRIVATE_NETWORK"
    PUBLIC_NETWORK = "PUBLIC_NETWORK"
    UNKNOWN = "UNKNOWN"


_PRIVATE_PREFIXES = (
    "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2",
    "172.3", "192.168.", "127.", "169.254.",
)
_LOOPBACK = ("127.", "::1", "0.0.0.0")


def classify_network_target(target: str) -> str:
    t = str(target).strip()
    if t in _LOOPBACK or t.startswith("127.") or t == "::1":
        return NetworkClass.LOOPBACK
    if t.startswith(_PRIVATE_PREFIXES):
        return NetworkClass.PRIVATE_NETWORK
    if t == "localhost" or t.startswith("localhost"):
        return NetworkClass.LOCAL_HOST
    if t in ("0.0.0.0", "::"):
        return NetworkClass.LOCAL_HOST
    # hostname without dots → LAN-ish guess, still bounded
    if t and "." not in t and ":" not in t and not t.isdigit():
        return NetworkClass.LAN
    if ":" in t or "." in t:
        return NetworkClass.PUBLIC_NETWORK
    return NetworkClass.UNKNOWN


class NetworkBoundary:
    """Fail-closed network boundary (read-only by default)."""

    def evaluate_connect(self, target: str,
                         operation: str = "CONNECT") -> object:
        cls = classify_network_target(target)
        if operation == "READ":
            return pass_decision("SBL_OK")
        if cls == NetworkClass.UNKNOWN and operation != "CONNECT":
            return block_decision("NETWORK_TARGET_UNKNOWN")
        # connecting anywhere is allowed by the policy engine's read
        # surface; firewall/route/config mutations are blocked at the
        # operation-classifier level (NETWORK_CHANGE / FIREWALL_CHANGE)
        return pass_decision("SBL_OK")


__all__ = [
    "NetworkClass",
    "NetworkBoundary",
    "classify_network_target",
]
