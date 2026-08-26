"""AgentRun isolation + idempotency (Phase 6 §13, §26)."""

import pytest

from agent.agent_integration.agent_run import (
    AgentRun,
    AgentRunKey,
    AgentRunRegistry,
    RunIsolationError,
    digest_of,
)


def _run_registry():
    return AgentRunRegistry()


def _create(runs, *, tenant="acme", user="u-1", task="task-1", step="step-1",
            agent="monitoring", generation=1, input_text="hello"):
    return runs.create(
        tenant_id=tenant, user_id=user, task_id=task, task_step_id=step,
        agent_id=agent, generation=generation, agent_definition_version=1,
        registry_digest="reg-v1", input_text=input_text,
    )


def test_run_binds_full_identity_and_digests():
    run = _create(_run_registry())
    assert run.key.tenant_id == "acme"
    assert run.registry_digest == "reg-v1"
    assert run.input_digest == digest_of("input", "hello")
    assert run.idempotency_key()


def test_cross_tenant_run_reuse_is_denied():
    runs = _run_registry()
    run = _create(runs, tenant="acme")
    # A run bound to acme can never be presented for another tenant.
    assert run.binds_to(tenant_id="other", user_id="u-1", task_id="task-1",
                        task_step_id="step-1", agent_id="monitoring", generation=1) is False
    with pytest.raises(RunIsolationError):
        runs.assert_binds(run, tenant_id="other", user_id="u-1", task_id="task-1",
                          agent_id="monitoring", generation=1)


@pytest.mark.parametrize(
    "field,other",
    [("user", "u-2"), ("task", "task-2"), ("agent", "research"), ("generation", 2)],
)
def test_cross_identity_reuse_is_denied(field, other):
    runs = _run_registry()
    run = _create(runs)
    kwargs = dict(tenant_id="acme", user_id="u-1", task_id="task-1",
                  agent_id="monitoring", generation=1)
    key_map = {"user": "user_id", "task": "task_id", "agent": "agent_id", "generation": "generation"}
    kwargs[key_map[field]] = other
    with pytest.raises(RunIsolationError):
        runs.assert_binds(run, **kwargs)  # type: ignore[arg-type]


def test_semantic_idempotency_duplicate_is_skipped():
    runs = _run_registry()
    run1 = _create(runs, input_text="same input")
    run2 = _create(runs, input_text="same input")
    # Same semantic identity -> same idempotency key.
    assert run1.idempotency_key() == run2.idempotency_key()
    runs.record_terminal(run1)
    assert runs.is_duplicate(run2) is True


def test_different_input_is_not_a_duplicate():
    runs = _run_registry()
    run1 = _create(runs, input_text="AAA")
    run2 = _create(runs, input_text="BBB")
    assert run1.idempotency_key() != run2.idempotency_key()
    runs.record_terminal(run1)
    assert runs.is_duplicate(run2) is False


def test_no_terminal_evidence_is_not_duplicate():
    runs = _run_registry()
    assert runs.is_duplicate(_create(runs)) is False


def test_run_key_requires_nonempty_bounded_identity():
    with pytest.raises(RunIsolationError):
        AgentRunKey(tenant_id="", user_id="u", task_id="t", task_step_id="s",
                    agent_id="a", generation=1)
    with pytest.raises(RunIsolationError):
        AgentRunKey(tenant_id="t", user_id="u", task_id="t", task_step_id="s",
                    agent_id="a", generation=0)


def test_run_requires_positive_definition_version():
    with pytest.raises(RunIsolationError):
        AgentRun(
            run_id="r", key=AgentRunKey(tenant_id="t", user_id="u", task_id="t",
                                        task_step_id="s", agent_id="a", generation=1),
            agent_definition_version=0, registry_digest="d", input_digest="i",
        )


def test_agent_run_type_is_checked():
    runs = _run_registry()
    with pytest.raises(RunIsolationError):
        runs.assert_binds("not-a-run", tenant_id="t", user_id="u", task_id="t",
                          agent_id="a", generation=1)  # type: ignore[arg-type]  # type: ignore[arg-type]