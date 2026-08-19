"""Sprint 1.3.12 — service restart foundation (exceptions)."""
from __future__ import annotations


class RestartFoundationError(Exception):
    """Base for all service_restart_foundation errors."""


class RestartDisabled(RestartFoundationError):
    """Execution attempted while restart authority is disabled (always in 1.3.12)."""


class RestartNotAdmitted(RestartFoundationError):
    """Service failed admission for restart eligibility."""


class RestartPlanInvalid(RestartFoundationError):
    """Restart plan failed binding / revalidation."""


class OrphanRisk(RestartFoundationError):
    """Orphan detected -> restart unsafe."""