"""Sprint 1.3.9 — Controlled Service Mutation Foundation (analysis/shadow only)."""
from .eligibility import evaluate
from .exceptions import ExecutionDisabled
from .graph import ServiceDependencyGraph
from .health import evaluate_health, validate_config
from .identity import verify_identity
from .models import (BlastRadius, Criticality, Eligibility, HealthStatus, IdentityResult,
                     Operation, RiskClass, ServiceChangePlan, ServiceClass, ValidatorResult)
from .plan import execute, plan_fingerprint, revalidate_required
from .registry import ServiceRegistry, build_default_profiles
