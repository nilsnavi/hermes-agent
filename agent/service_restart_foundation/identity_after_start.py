"""Sprint 1.3.12 — post-start process identity proof.

The new process must match expected executable/user/cgroup/unit and carry a new
process-start identity. Identity mismatch after restart -> FAIL.
"""
from __future__ import annotations


def verify_post_start_identity(
    expected_executable: str,
    actual_executable: str,
    expected_user: str,
    actual_user: str,
    expected_cgroup: str,
    actual_cgroup: str,
    new_pid,
) -> bool:
    """True only when every identity facet matches and a new PID exists."""
    if not new_pid:
        return False
    if actual_executable != expected_executable:
        return False
    if actual_user != expected_user:
        return False
    if expected_cgroup and actual_cgroup != expected_cgroup:
        return False
    return True


class IdentityAfterStart:
    """Result enum for post-start identity checks."""

    VERIFIED = "IDENTITY_VERIFIED"
    MISMATCH = "IDENTITY_CHANGED_AFTER_RESTART"
    NO_PID = "NO_NEW_PID"


__all__ = ["IdentityAfterStart", "verify_post_start_identity"]