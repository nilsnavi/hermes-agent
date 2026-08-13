"""Execution policy + failure taxonomy tests (Sprint 1.0.5)."""

from agent.execution.registry import SideEffectClass, ToolMetadata
from agent.orchestrator.policy import (
    ConservativeRiskPolicy,
    ExecutionPolicy,
    FailureClass,
    RiskDecision,
    classify_failure,
    may_retry,
)
from agent.runtime.context import TaskContext
from agent.execution.models import ExecutionStep


def test_policy_conservative_defaults():
    p = ExecutionPolicy()
    assert p.max_steps == 20
    assert p.max_tool_calls == 10
    assert p.max_replans == 2
    assert p.max_failures == 3
    assert p.max_runtime_seconds == 300.0
    assert p.max_retries == 0  # no auto-retry by default
    assert p.allow_replanning is False


def test_classify_timeout_retryable():
    md = ToolMetadata()  # not idempotent
    assert classify_failure("timeout", md) is FailureClass.RETRYABLE


def test_classify_permission_denied_non_retryable():
    md = ToolMetadata(idempotent=True, side_effect_class=SideEffectClass.READ_ONLY)
    assert classify_failure("permission_denied", md) is FailureClass.NON_RETRYABLE
    assert classify_failure("not_allowed", md) is FailureClass.NON_RETRYABLE


def test_classify_failure_retryable_only_for_idempotent_read_only():
    assert classify_failure("failure", ToolMetadata()) is FailureClass.NON_RETRYABLE
    assert classify_failure("failure", ToolMetadata(idempotent=True)) \
        is FailureClass.NON_RETRYABLE
    assert classify_failure(
        "failure",
        ToolMetadata(idempotent=True, side_effect_class=SideEffectClass.READ_ONLY),
    ) is FailureClass.RETRYABLE


def test_may_retry_matrix():
    policy = ExecutionPolicy(max_retries=1)
    ro = ToolMetadata(idempotent=True, side_effect_class=SideEffectClass.READ_ONLY)
    rw = ToolMetadata(idempotent=True, side_effect_class=SideEffectClass.REVERSIBLE_WRITE)
    irreversible = ToolMetadata(idempotent=True,
                                side_effect_class=SideEffectClass.IRREVERSIBLE_WRITE)
    unknown = ToolMetadata(idempotent=True)  # UNKNOWN class
    non_idempotent = ToolMetadata(idempotent=False,
                                  side_effect_class=SideEffectClass.READ_ONLY)

    assert may_retry(FailureClass.RETRYABLE, ro, attempts_used=1, policy=policy) is True
    assert may_retry(FailureClass.RETRYABLE, rw, attempts_used=1, policy=policy) is True
    # IRREVERSIBLE_WRITE / UNKNOWN / non-idempotent → NEVER
    assert may_retry(FailureClass.RETRYABLE, irreversible, 1, policy) is False
    assert may_retry(FailureClass.RETRYABLE, unknown, 1, policy) is False
    assert may_retry(FailureClass.RETRYABLE, non_idempotent, 1, policy) is False
    # non-retryable class never retries regardless of metadata
    assert may_retry(FailureClass.NON_RETRYABLE, ro, 1, policy) is False


def test_may_retry_bounded_by_max_retries():
    policy = ExecutionPolicy(max_retries=2)
    ro = ToolMetadata(idempotent=True, side_effect_class=SideEffectClass.READ_ONLY)
    assert may_retry(FailureClass.RETRYABLE, ro, attempts_used=1, policy=policy) is True
    assert may_retry(FailureClass.RETRYABLE, ro, attempts_used=2, policy=policy) is True
    assert may_retry(FailureClass.RETRYABLE, ro, attempts_used=3, policy=policy) is False
    # default policy has NO retries
    assert may_retry(FailureClass.RETRYABLE, ro, 1, ExecutionPolicy()) is False


def _step(tool, arguments=None):
    return ExecutionStep(id="s1", name="s1", description="", tool=tool,
                         arguments=arguments or {})


def test_conservative_risk_allow():
    policy = ConservativeRiskPolicy()
    ctx = TaskContext(goal="g", allowed_tools=["search"], risk_level="low")
    md = ToolMetadata(side_effect_class=SideEffectClass.READ_ONLY)
    assert policy.evaluate(_step("search"), md, ctx) is RiskDecision.ALLOW


def test_conservative_risk_critical_requires_approval():
    policy = ConservativeRiskPolicy()
    ctx = TaskContext(goal="g", risk_level="critical")
    md = ToolMetadata(side_effect_class=SideEffectClass.READ_ONLY)
    assert policy.evaluate(_step("search"), md, ctx) is RiskDecision.REQUIRE_APPROVAL


def test_conservative_risk_irreversible_requires_approval():
    policy = ConservativeRiskPolicy()
    ctx = TaskContext(goal="g", risk_level="low")
    md = ToolMetadata(side_effect_class=SideEffectClass.IRREVERSIBLE_WRITE)
    assert policy.evaluate(_step("delete"), md, ctx) is RiskDecision.REQUIRE_APPROVAL


def test_conservative_risk_deny_list():
    policy = ConservativeRiskPolicy()
    ctx = TaskContext(goal="g", metadata={"deny_tools": ["delete"]})
    md = ToolMetadata(side_effect_class=SideEffectClass.READ_ONLY)
    assert policy.evaluate(_step("delete"), md, ctx) is RiskDecision.DENY
    assert policy.evaluate(_step("search"), md, ctx) is RiskDecision.ALLOW
