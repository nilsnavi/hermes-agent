"""Sprint 1.3.12 — restart risk, with mandatory monotonicity.

Restart baseline risk must NEVER be lower than reload risk. A profile is not
allowed to lower restart risk (no risk reduction via profile).
"""
from __future__ import annotations

# Risk taxonomy ranks (lowest→highest).
_ORDER = {
    "LOW": 0,
    "MEDIUM": 1,
    "MEDIUM_MUTATION": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

# Restart baseline is always HIGH for 1.3.12 (higher than the MEDIUM_MUTATION
# reload baseline). Never derived from profile input to prevent risk gaming.
_RESTART_BASELINE = "HIGH"
_RELOAD_BASELINE = "MEDIUM_MUTATION"


def _rank(c: str) -> int:
    return _ORDER.get(c, _ORDER["MEDIUM_MUTATION"])


def resolve_risk_class(op: str) -> str:
    """Resolve the baseline risk class for an operation ('reload'|'restart')."""
    op = (op or "").lower()
    if op == "restart":
        return _RESTART_BASELINE  # HIGH
    if op == "reload":
        return _RELOAD_BASELINE  # MEDIUM_MUTATION
    return _RESTART_BASELINE


def risk_not_below(profile_risk: str, reload_risk: str) -> bool:
    """True when profile restart risk >= reload risk (monotonicity satisfied)."""
    return _rank(profile_risk) >= _rank(reload_risk)


def restart_risk_acceptable(profile_risk: str) -> bool:
    """A restart profile risk is acceptable only if >= reload baseline."""
    return risk_not_below(profile_risk, _RELOAD_BASELINE)


__all__ = [
    "resolve_risk_class",
    "restart_risk_acceptable",
    "risk_not_below",
]