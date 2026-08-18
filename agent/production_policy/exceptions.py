"""Sprint 1.3.8 — Limited Production Mutation Policy (exceptions)."""


class ProductionPolicyError(Exception):
    """Base for policy-layer errors (never grants authority)."""


class PolicyDenied(ProductionPolicyError):
    """A mutation was denied (wrong profile/target/op/risk/...)."""


class ProfileDisabled(ProductionPolicyError):
    pass


class TargetNotRegistered(ProductionPolicyError):
    pass


class OperationNotAllowed(ProductionPolicyError):
    pass


class BudgetExceeded(ProductionPolicyError):
    pass


class CircuitBreakerOpen(ProductionPolicyError):
    pass


class ApprovalInvalid(ProductionPolicyError):
    pass


class BlastRadiusBlocked(ProductionPolicyError):
    pass


class ConsumerUnknownBlocked(ProductionPolicyError):
    pass
